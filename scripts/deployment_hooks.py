"""Implementation of the azd hooks, with lazy Azure imports for offline testing.

preprovision owns .azure/azd-hooks/.venv and its requirements fingerprint. pip uses
an existing protected/CFS or Azure Artifacts configuration, otherwise the CFS feed.
postprovision validates outputs without accessing private data planes.
postdeploy uses AzureDeveloperCliCredential to start and monitor one private seed
job execution, restarts the application revision to clear cached local fallbacks,
then checks the frontend, its entry asset, Azure health, and scenario. It never
starts a model workflow. APP_URL takes precedence over SERVICE_APP_ENDPOINT_URL.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
PROTECTED_FEED = "https://packagefeedproxy.microsoft.io/pypi/simple"
# Named AZURE_TOKEN_CREDENTIALS selection requires azure-identity 1.24+.
HOOK_REQUIREMENTS = ("azure-identity>=1.24.0",)
REQUIRED_OUTPUTS = (
    "AZURE_AI_PROJECT_ENDPOINT", "AZURE_OPENAI_ENDPOINT", "MODEL_DEPLOYMENT_NAME",
    "EMBEDDING_DEPLOYMENT_NAME", "COSMOS_ENDPOINT", "COSMOS_DATABASE",
    "SEARCH_ENDPOINT", "SEARCH_INDEX_NAME", "STORAGE_BLOB_ENDPOINT",
    "KNOWLEDGE_CONTAINER", "FOUNDRY_AGENT_PREFIX",
)
TRANSIENT_STATUSES = {401, 403, 408, 429, 500, 502, 503, 504}
ARM_ENDPOINT = "https://management.azure.com"
ARM_API_VERSION = "2024-03-01"
SEED_JOB_TIMEOUT = 1800

DEPENDENCY_PROBE = r"""
import importlib
import importlib.metadata
from pathlib import Path
import sys
from pip._vendor.packaging.requirements import Requirement

missing = []
lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() + sys.argv[2:]
for line in lines:
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    requirement = Requirement(line)
    if requirement.url:
        raise ValueError("Direct package URLs are not allowed in hook requirements")
    if requirement.marker and not requirement.marker.evaluate():
        continue
    try:
        version = importlib.metadata.version(requirement.name)
        if not requirement.specifier.contains(version, prereleases=True):
            missing.append(str(requirement))
    except importlib.metadata.PackageNotFoundError:
        missing.append(str(requirement))
for module in ("azure.identity", "azure.cosmos", "azure.search.documents",
               "azure.storage.blob", "azure.ai.projects", "openai", "dotenv",
               "fastapi", "aiohttp", "httpx"):
    try:
        importlib.import_module(module)
    except ImportError:
        missing.append(module)
if missing:
    print("Missing or incompatible Python dependencies: " + ", ".join(missing))
    sys.exit(10)
"""


def run_native(command: list[str], *, env: dict[str, str] | None = None,
               capture: bool = False) -> subprocess.CompletedProcess:
    """Every unexpected native exit is fatal, including pip/config/auth failures."""
    return subprocess.run(
        command, cwd=ROOT, env=env, check=True, text=True, capture_output=capture,
    )


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _approved_feed(value: str) -> bool:
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname:
        return False
    if url.hostname == "packagefeedproxy.microsoft.io":
        return url.path.rstrip("/") == "/pypi/simple"
    return (
        (url.hostname == "pkgs.dev.azure.com" or url.hostname.endswith(".pkgs.visualstudio.com"))
        and "/_packaging/" in url.path
        and url.path.rstrip("/").endswith("/pypi/simple")
    )


def pip_environment(python: Path, root: Path) -> dict[str, str]:
    env = dict(os.environ)
    if not env.get("PIP_CONFIG_FILE"):
        for name in ("pip.ini", "pip.conf"):
            config = root / name
            if config.is_file():
                env["PIP_CONFIG_FILE"] = str(config)
                break
    result = run_native([str(python), "-m", "pip", "config", "list"], env=env, capture=True)
    config_values = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            config_values[key.strip()] = ast.literal_eval(value.strip())

    def setting(name: str) -> str:
        return env.get(
            "PIP_" + name.upper().replace("-", "_"),
            config_values.get("install." + name, config_values.get("global." + name, "")),
        )

    index = setting("index-url") or PROTECTED_FEED
    extras = setting("extra-index-url")
    if not all(_approved_feed(feed) for feed in [index, *extras.split()]):
        raise RuntimeError(
            "pip index configuration is not approved. Use the protected Microsoft "
            "feed or the repository's Azure Artifacts feed; request a CFS exception "
            "if a package is unavailable. No public fallback is allowed."
        )
    if setting("find-links"):
        raise RuntimeError("pip find-links is not supported: hooks require protected package feeds.")
    env["PIP_INDEX_URL"] = index
    env["PIP_EXTRA_INDEX_URL"] = extras
    env["PIP_NO_INPUT"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def dependencies_available(python: Path, manifest: Path) -> bool:
    try:
        run_native([str(python), "-c", DEPENDENCY_PROBE, str(manifest), *HOOK_REQUIREMENTS])
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 10:
            return False
        raise
    return True


def preprovision(root: Path = ROOT) -> None:
    version = run_native(["azd", "version"], capture=True)
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)", version.stdout)
    if not match or tuple(map(int, match.groups())) < (1, 25, 0):
        raise RuntimeError("Azure Developer CLI (azd) 1.25+ is required.")
    manifest = root / "src" / "backend" / "requirements.txt"
    fingerprint = hashlib.sha256(
        manifest.read_bytes() + "\n".join(HOOK_REQUIREMENTS).encode()
    ).hexdigest()
    venv = root / ".azure" / "azd-hooks" / ".venv"
    python = venv_python(venv)
    if not python.is_file():
        print(f"Creating deployment Python environment: {venv}", flush=True)
        run_native([sys.executable, "-m", "venv", str(venv)])
    stamp = venv / ".requirements.sha256"
    available = dependencies_available(python, manifest)
    changed = not stamp.is_file() or stamp.read_text(encoding="utf-8").strip() != fingerprint
    if changed or not available:
        env = pip_environment(python, root)
        print("Installing deployment requirements (missing dependencies or changed manifest).", flush=True)
        run_native(
            [str(python), "-m", "pip", "install", "-r", str(manifest), *HOOK_REQUIREMENTS],
            env=env,
        )
        if not dependencies_available(python, manifest):
            raise RuntimeError("Deployment dependencies remain missing after pip install.")
        run_native([str(python), "-m", "pip", "check"], env=env)
        stamp.write_text(fingerprint + "\n", encoding="utf-8")
    else:
        run_native([str(python), "-m", "pip", "check"])
        print("Deployment dependencies are installed and unchanged; skipping pip install.")


def require_outputs() -> None:
    missing = [key for key in REQUIRED_OUTPUTS if not os.getenv(key, "").strip()]
    if missing:
        raise RuntimeError("Missing azd output(s): " + ", ".join(missing))


def postprovision() -> None:
    require_outputs()
    deployment_resource_paths()
    if not venv_python(ROOT / ".azure" / "azd-hooks" / ".venv").is_file():
        raise RuntimeError("Deployment environment is missing; run the preprovision hook first.")
    print(
        "Deployment outputs validated. Private data-plane seeding and agent provisioning "
        "are deferred to the Container Apps seed job during postdeploy.",
        flush=True,
    )


def _resource_name(value, label: str, pattern: str, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit or not re.fullmatch(pattern, value):
        raise ValueError(f"{label} is missing or is not a valid resource identifier.")
    return value


def deployment_resource_paths() -> tuple[str, str]:
    subscription = _resource_name(
        os.getenv("AZURE_SUBSCRIPTION_ID"), "AZURE_SUBSCRIPTION_ID",
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", 36,
    )
    if UUID(subscription).int == 0:
        raise ValueError("AZURE_SUBSCRIPTION_ID must be a nonzero GUID.")
    group = _resource_name(
        os.getenv("AZURE_RESOURCE_GROUP"), "AZURE_RESOURCE_GROUP",
        r"[A-Za-z0-9_()\-][A-Za-z0-9_().\-]*", 90,
    )
    if group.endswith("."):
        raise ValueError("AZURE_RESOURCE_GROUP cannot end with a period.")
    names = [
        _resource_name(os.getenv(key), key, r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", 32)
        for key in ("AZURE_SEED_JOB_NAME", "AZURE_CONTAINER_APP_NAME")
    ]
    base = f"/subscriptions/{subscription}/resourceGroups/{group}/providers/Microsoft.App"
    return f"{base}/jobs/{names[0]}", f"{base}/containerApps/{names[1]}"


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Private seed job deployment timed out.")
    return remaining


class _NoArmRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an ARM bearer token to a redirect target.
        return None


class ArmClient:
    def __init__(self, credential):
        self.credential = credential
        self.opener = build_opener(_NoArmRedirects())

    def request(self, method: str, path: str, deadline: float):
        _remaining(deadline)
        try:
            token = self.credential.get_token(ARM_ENDPOINT + "/.default")
        except Exception:
            raise RuntimeError("ARM authentication with the Azure Developer CLI identity failed.") from None
        request = Request(
            ARM_ENDPOINT + path, method=method,
            headers={
                "Authorization": "Bearer " + token.token,
                "Accept": "application/json", "Content-Type": "application/json",
            },
        )
        try:
            with self.opener.open(request, timeout=min(30, _remaining(deadline))) as response:
                status = response.status
                location = response.headers.get("Location")
                body = response.read(2_000_001)
        except HTTPError as exc:
            raise RuntimeError(f"ARM {method} request failed (HTTP {exc.code}).") from None
        except (OSError, URLError, ValueError):
            raise RuntimeError(f"ARM {method} request failed without a valid response.") from None
        if status not in {200, 202}:
            raise RuntimeError(f"ARM {method} returned unexpected HTTP {status}.")
        if len(body) > 2_000_000:
            raise RuntimeError("ARM response exceeds the size limit.")
        try:
            result = json.loads(body) if body.strip() else None
        except (ValueError, UnicodeError):
            raise RuntimeError("ARM returned malformed JSON.") from None
        if body.strip() and not isinstance(result, dict):
            raise RuntimeError("ARM response must be a JSON object.")
        if isinstance(result, dict) and "error" in result:
            raise RuntimeError("ARM returned an error response.")
        return status, result, location


def _api(path: str) -> str:
    return path + "?api-version=" + ARM_API_VERSION


def _operation_location(location, job_path: str) -> str:
    if not isinstance(location, str):
        raise RuntimeError("ARM job start did not return an operation Location.")
    parsed = urlsplit(location)
    subscription_path = job_path.split("/resourceGroups/", 1)[0]
    allowed_paths = (
        re.escape(job_path) + r"/[A-Za-z0-9/_-]+",
        re.escape(subscription_path)
        + r"/providers/Microsoft\.App/locations/[a-z0-9-]+/operation(?:Results|Statuses)/[A-Za-z0-9-]+",
    )
    if (
        parsed.scheme != "https" or parsed.netloc != "management.azure.com"
        or parsed.fragment or not any(re.fullmatch(pattern, parsed.path) for pattern in allowed_paths)
        or any(part in {".", ".."} for part in parsed.path.split("/"))
        or parse_qs(parsed.query) != {"api-version": [ARM_API_VERSION]}
    ):
        raise RuntimeError("ARM job start returned an unsafe operation Location.")
    return parsed.path + "?" + parsed.query


def _execution_name(body, job_path: str) -> str:
    if not isinstance(body, dict):
        raise RuntimeError("ARM job start did not return an execution object.")
    name = _resource_name(body.get("name"), "Job execution name", r"[a-z0-9][a-z0-9-]*", 100)
    if not name.startswith(job_path.rsplit("/", 1)[-1] + "-"):
        raise RuntimeError("ARM returned an execution for a different seed job.")
    expected_id = job_path + "/executions/" + name
    if "id" in body and (
        not isinstance(body["id"], str) or body["id"].lower() != expected_id.lower()
    ):
        raise RuntimeError("ARM returned a mismatched seed job execution ID.")
    return name


def run_private_seed_job(client: ArmClient, job_path: str, *, timeout: float = SEED_JOB_TIMEOUT,
                         interval: float = 10) -> None:
    if timeout <= 0 or interval <= 0:
        raise ValueError("Seed job timeout and poll interval must be positive.")
    deadline = time.monotonic() + timeout
    status, body, location = client.request("POST", _api(job_path + "/start"), deadline)
    # Start is an ARM LRO; only its returned result may select the new execution.
    while status == 202 and not (isinstance(body, dict) and "name" in body):
        operation = _operation_location(location, job_path)
        time.sleep(min(interval, _remaining(deadline)))
        status, body, next_location = client.request("GET", operation, deadline)
        location = next_location or location
    name = _execution_name(body, job_path)
    execution_path = _api(job_path + "/executions/" + name)
    print(f"Waiting for private seed job execution {name}.", flush=True)
    while True:
        _remaining(deadline)
        status, execution, _ = client.request("GET", execution_path, deadline)
        if status != 200 or _execution_name(execution, job_path) != name:
            raise RuntimeError("ARM returned a different or incomplete seed job execution.")
        properties = execution.get("properties")
        state = properties.get("status") if isinstance(properties, dict) else None
        if not isinstance(state, str) or state not in {
            "Running", "Processing", "Stopped", "Degraded", "Failed", "Unknown", "Succeeded",
        }:
            raise RuntimeError("ARM returned a malformed seed job execution status.")
        if state == "Succeeded":
            print("Private seed job succeeded.", flush=True)
            return
        if state in {"Failed", "Stopped"}:
            raise RuntimeError(f"Private seed job execution {name} {state}.")
        time.sleep(min(interval, _remaining(deadline)))


def restart_application(client: ArmClient, app_path: str, *, timeout: float = 300) -> None:
    deadline = time.monotonic() + timeout
    status, app, _ = client.request("GET", _api(app_path), deadline)
    properties = app.get("properties") if isinstance(app, dict) else None
    if status != 200 or not isinstance(properties, dict):
        raise RuntimeError("ARM returned a malformed Container App response.")
    revision = _resource_name(
        properties.get("latestReadyRevisionName"), "latestReadyRevisionName",
        r"[a-z0-9][a-z0-9-]*", 100,
    )
    if not revision.startswith(app_path.rsplit("/", 1)[-1] + "-"):
        raise RuntimeError("ARM returned a ready revision for a different Container App.")
    status, _, _ = client.request("POST", _api(app_path + f"/revisions/{revision}/restart"), deadline)
    if status != 200:
        raise RuntimeError("ARM did not confirm the Container App revision restart.")
    print("Application revision restarted after seeding; checking Azure-backed readiness.", flush=True)


def postdeploy() -> None:
    url = os.getenv("APP_URL", "").strip() or os.getenv("SERVICE_APP_ENDPOINT_URL", "").strip()
    if not url:
        raise RuntimeError("Missing azd output: APP_URL or SERVICE_APP_ENDPOINT_URL.")
    job_path, app_path = deployment_resource_paths()
    from azure.identity import AzureDeveloperCliCredential

    with AzureDeveloperCliCredential(
        tenant_id=os.getenv("AZURE_TENANT_ID") or None, process_timeout=30,
    ) as credential:
        client = ArmClient(credential)
        run_private_seed_job(client, job_path)
        restart_application(client, app_path)
    # Restart invalidates startup-cached Search fallback. Strict HTTP polling is
    # the final readiness gate, not a successful ARM request or a previous run.
    verify_application(url)


def retry_azure(operation, label: str, *, attempts: int = 7, delay: float = 5):
    """Retry only service/auth HTTP statuses that can settle after provisioning."""
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            wait = _retry_delay(exc, label, attempt, attempts, delay)
            if wait is None:
                raise
            time.sleep(wait)


async def retry_azure_async(operation, label: str, *, attempts: int = 7, delay: float = 5):
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except Exception as exc:
            wait = _retry_delay(exc, label, attempt, attempts, delay)
            if wait is None:
                raise
            await asyncio.sleep(wait)


def _retry_delay(exc: Exception, label: str, attempt: int, attempts: int, delay: float):
    status = getattr(exc, "status_code", None)
    if status not in TRANSIENT_STATUSES or attempt == attempts:
        return None
    wait = min(delay * (2 ** (attempt - 1)), 30)
    reason = "authorization/RBAC propagation" if status in {401, 403} else "transient service response"
    print(
        f"{label}: HTTP {status} ({reason}); retry {attempt}/{attempts - 1} in {wait}s.",
        flush=True,
    )
    return wait


class VerificationError(RuntimeError):
    pass


class _FrontendParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = False
        self.script = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.root |= tag == "div" and attrs.get("id") == "root"
        if tag == "script" and attrs.get("type") == "module" and attrs.get("src"):
            self.script = attrs["src"]


def verify_application(base_url: str, *, timeout: float = 300, interval: float = 5) -> None:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"} or not parsed.netloc
        or parsed.username or parsed.password or parsed.query or parsed.fragment
    ):
        raise ValueError("APP_URL / SERVICE_APP_ENDPOINT_URL must be an HTTP(S) application URL.")
    base_url = base_url.rstrip("/") + "/"
    deadline = time.monotonic() + timeout

    def fetch(url: str) -> tuple[str, str]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Application verification deadline exceeded.")
        with urlopen(url, timeout=min(15, remaining)) as response:
            if response.status != 200:
                raise VerificationError(f"{url}: expected HTTP 200, received {response.status}")
            content_type = response.headers.get("Content-Type", "").lower()
            content = response.read(2_000_001)
            if len(content) > 2_000_000:
                raise VerificationError(f"{url}: response exceeds verification size limit")
            return content_type, content.decode("utf-8")

    def fetch_json(path: str) -> dict:
        content_type, body = fetch(urljoin(base_url, path))
        if "application/json" not in content_type:
            raise VerificationError(f"{path}: expected JSON, received {content_type}")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise VerificationError(f"{path}: expected a JSON object")
        return result

    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            content_type, html = fetch(base_url)
            parser = _FrontendParser()
            parser.feed(html)
            if (
                "text/html" not in content_type or not parser.root or not parser.script
                or "Grocery Supply Disruption Response" not in html
            ):
                raise VerificationError("Frontend did not return the built grocery application.")
            asset_url = urljoin(base_url, parser.script)
            if (urlsplit(asset_url).scheme, urlsplit(asset_url).netloc) != (parsed.scheme, parsed.netloc):
                raise VerificationError("Frontend entry asset is not hosted by this application.")
            asset_type, asset = fetch(asset_url)
            if "javascript" not in asset_type or not asset.strip() or asset.lstrip().startswith("<"):
                raise VerificationError("Frontend entry JavaScript asset is missing or invalid.")
            health = fetch_json("api/health")
            expected = {
                "status": "healthy", "openAiConfigured": True,
                "dataSource": "cosmos", "knowledgeSource": "azure-ai-search",
            }
            for field, value in expected.items():
                if health.get(field) != value:
                    raise VerificationError(f"/api/health: {field} must be {value!r}, got {health.get(field)!r}")
            if (
                not isinstance(health.get("model"), str) or not health["model"].strip()
                or type(health.get("agentCount")) is not int or health["agentCount"] <= 0
            ):
                raise VerificationError("/api/health: model or agentCount is missing/invalid.")
            scenario = fetch_json("api/scenario")
            signal, graph, agents = (scenario.get(key) for key in ("signal", "graph", "agents"))
            if not isinstance(signal, dict) or not signal.get("id"):
                raise VerificationError("/api/scenario: seeded signal data is missing.")
            if not isinstance(graph, dict) or any(
                not isinstance(graph.get(key), list) or not graph[key] for key in ("nodes", "edges")
            ):
                raise VerificationError("/api/scenario: graph nodes/edges are missing.")
            if not isinstance(agents, list) or not agents:
                raise VerificationError("/api/scenario: agents are missing.")
            if any(not isinstance(node, dict) or not node.get("id") for node in graph["nodes"]):
                raise VerificationError("/api/scenario: graph node data is invalid.")
            if any(
                not isinstance(edge, dict) or not edge.get("from") or not edge.get("to")
                for edge in graph["edges"]
            ):
                raise VerificationError("/api/scenario: graph edge data is invalid.")
            if any(
                not isinstance(agent, dict) or not agent.get("nodeId") or not agent.get("name")
                for agent in agents
            ):
                raise VerificationError("/api/scenario: agent data is invalid.")
            print("Application verification passed: frontend, entry asset, Azure health, and scenario.")
            return
        except HTTPError as exc:
            if exc.code not in {404, 408, 429, 500, 502, 503, 504}:
                raise
            last_error = f"HTTP {exc.code} while waiting for the deployed application"
        except (VerificationError, URLError, TimeoutError, ConnectionError, ValueError) as exc:
            last_error = str(exc)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        print(f"Application not ready: {last_error}; retrying in {min(interval, remaining):g}s.", flush=True)
        time.sleep(min(interval, remaining))
    raise VerificationError(f"Application verification timed out after {timeout:g}s: {last_error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preprovision", "postprovision", "postdeploy"), required=True)
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 11):
            raise RuntimeError("Python 3.11+ is required.")
        if args.phase == "preprovision":
            preprovision()
        elif args.phase == "postprovision":
            postprovision()
        else:
            postdeploy()
        return 0
    except Exception as exc:
        print(f"{args.phase} failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
