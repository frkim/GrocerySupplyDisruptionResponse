"""Local-only deployment hook regression tests: python -m unittest discover -s tests -p test_deployment_hooks.py."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from urllib.error import HTTPError
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import deployment_hooks as hooks, seed  # noqa: E402


class ServiceError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def module(name, **attributes):
    result = ModuleType(name)
    result.__dict__.update(attributes)
    return result


class QuietTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("sys.stdout", new=io.StringIO()))
        self.enterContext(patch("sys.stderr", new=io.StringIO()))


class BootstrapTests(QuietTest):
    def setUp(self):
        super().setUp()
        self.root = ROOT / ".cache" / ("deployment-hooks-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)
        self.manifest = self.root / "src" / "backend" / "requirements.txt"
        self.manifest.parent.mkdir(parents=True)
        self.manifest.write_text("azure-identity>=1.19.0\n", encoding="utf-8")
        self.venv = self.root / ".azure" / "azd-hooks" / ".venv"
        self.python = hooks.venv_python(self.venv)
        self.python.parent.mkdir(parents=True)
        self.python.touch()
        self.stamp = self.venv / ".requirements.sha256"
        self.fingerprint = hashlib.sha256(
            self.manifest.read_bytes() + "\n".join(hooks.HOOK_REQUIREMENTS).encode()
        ).hexdigest()
        self.native = self.enterContext(patch.object(
            hooks, "run_native", return_value=SimpleNamespace(stdout="azd version 1.25.2"),
        ))
        self.available = self.enterContext(patch.object(hooks, "dependencies_available", return_value=True))
        self.pip_env = self.enterContext(patch.object(hooks, "pip_environment", return_value={}))

    def test_unchanged_complete_environment_does_not_install(self):
        self.stamp.write_text(self.fingerprint, encoding="utf-8")
        hooks.preprovision(self.root)
        self.assertFalse(any("install" in call.args[0] for call in self.native.call_args_list))
        self.pip_env.assert_not_called()

    def test_changed_manifest_installs_and_stamps(self):
        self.stamp.write_text("previous manifest", encoding="utf-8")
        hooks.preprovision(self.root)
        self.assertTrue(any("install" in call.args[0] for call in self.native.call_args_list))
        self.assertEqual(self.fingerprint, self.stamp.read_text().strip())

    def test_missing_dependencies_install_even_with_current_stamp(self):
        self.stamp.write_text(self.fingerprint, encoding="utf-8")
        self.available.side_effect = [False, True]
        hooks.preprovision(self.root)
        self.pip_env.assert_called_once()

    def test_native_pip_failure_is_fatal_without_success_stamp(self):
        self.native.side_effect = [
            SimpleNamespace(stdout="azd version 1.25.2"),
            subprocess.CalledProcessError(9, ["pip", "install"]),
        ]
        with self.assertRaises(subprocess.CalledProcessError):
            hooks.preprovision(self.root)
        self.assertFalse(self.stamp.exists())

    def test_missing_environment_is_created(self):
        self.python.unlink()
        hooks.preprovision(self.root)
        commands = [call.args[0] for call in self.native.call_args_list]
        self.assertIn([sys.executable, "-m", "venv", str(self.venv)], commands)

    def test_unsupported_azd_version_fails_before_install(self):
        self.native.return_value.stdout = "azd version 1.24.9"
        with self.assertRaisesRegex(RuntimeError, "1.25"):
            hooks.preprovision(self.root)
        self.available.assert_not_called()


class ConfigurationTests(QuietTest):
    def test_missing_outputs_fail_without_running_seeding(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(hooks, "run_native") as native:
            self.assertEqual(hooks.main(["--phase", "postprovision"]), 1)
        native.assert_not_called()

    def test_postprovision_uses_azd_identity_and_propagates_native_error(self):
        original_credential = os.getenv("AZURE_TOKEN_CREDENTIALS")
        outputs = {key: "configured" for key in hooks.REQUIRED_OUTPUTS}
        with patch.dict(os.environ, outputs, clear=True), patch.object(Path, "is_file", return_value=True):
            with patch.object(hooks, "run_native") as native:
                native.side_effect = [None, subprocess.CalledProcessError(8, ["provision_agents.py"])]
                self.assertEqual(hooks.main(["--phase", "postprovision"]), 1)
                self.assertEqual(native.call_count, 2)
                for call in native.call_args_list:
                    self.assertEqual(call.kwargs["env"]["AZURE_TOKEN_CREDENTIALS"], "AzureDeveloperCliCredential")
                    self.assertEqual(call.kwargs["env"]["COSMOS_ENDPOINT"], "configured")
        self.assertEqual(os.getenv("AZURE_TOKEN_CREDENTIALS"), original_credential)

    def test_seed_failure_stops_before_agent_provisioning(self):
        outputs = {key: "configured" for key in hooks.REQUIRED_OUTPUTS}
        with patch.dict(os.environ, outputs, clear=True), patch.object(Path, "is_file", return_value=True):
            with patch.object(hooks, "run_native", side_effect=subprocess.CalledProcessError(5, ["seed.py"])) as native:
                with self.assertRaises(subprocess.CalledProcessError):
                    hooks.postprovision()
                self.assertEqual(native.call_count, 1)

    def test_missing_environment_fails_explicitly(self):
        with patch.dict(os.environ, {key: "ok" for key in hooks.REQUIRED_OUTPUTS}, clear=True):
            with patch.object(Path, "is_file", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "preprovision"):
                    hooks.postprovision()

    def test_dependency_probe_only_treats_documented_missing_exit_as_missing(self):
        for code, expected_missing in ((10, True), (1, False), (27, False)):
            with self.subTest(code=code):
                with patch.object(hooks, "run_native", side_effect=subprocess.CalledProcessError(code, ["python"])):
                    if expected_missing:
                        self.assertFalse(hooks.dependencies_available(Path("python"), Path("requirements.txt")))
                    else:
                        with self.assertRaises(subprocess.CalledProcessError):
                            hooks.dependencies_available(Path("python"), Path("requirements.txt"))

    def test_native_runner_checks_exit(self):
        with patch.object(subprocess, "run", side_effect=subprocess.CalledProcessError(3, ["example"])) as native:
            with self.assertRaises(subprocess.CalledProcessError):
                hooks.run_native(["example"])
            self.assertTrue(native.call_args.kwargs["check"])

    def pip_environment(self, values="", env=None):
        with patch.dict(os.environ, env or {}, clear=True), patch.object(Path, "is_file", return_value=False):
            with patch.object(hooks, "run_native", return_value=SimpleNamespace(stdout=values)):
                return hooks.pip_environment(Path("python"), ROOT)

    def test_default_feed_is_protected(self):
        self.assertEqual(self.pip_environment()["PIP_INDEX_URL"], hooks.PROTECTED_FEED)

    def test_existing_azure_artifacts_is_respected(self):
        feed = "https://pkgs.dev.azure.com/org/project/_packaging/team/pypi/simple/"
        self.assertEqual(self.pip_environment(f"global.index-url='{feed}'")["PIP_INDEX_URL"], feed)

    def test_unapproved_primary_or_extra_feed_is_rejected(self):
        for env in (
            {"PIP_INDEX_URL": "https://unapproved.example/simple"},
            {"PIP_INDEX_URL": hooks.PROTECTED_FEED, "PIP_EXTRA_INDEX_URL": "https://unapproved.example/simple"},
            {"PIP_FIND_LINKS": "https://unapproved.example/packages"},
        ):
            with self.subTest(env=env), self.assertRaises(RuntimeError):
                self.pip_environment(env=env)

    def test_repository_pip_configuration_is_preferred(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, "is_file", return_value=True):
            with patch.object(hooks, "run_native", return_value=SimpleNamespace(stdout="")) as native:
                hooks.pip_environment(Path("python"), ROOT)
                self.assertEqual(native.call_args.kwargs["env"]["PIP_CONFIG_FILE"], str(ROOT / "pip.ini"))


class RetryTests(QuietTest):
    def test_rbac_failure_retries_with_reason(self):
        operation = Mock(side_effect=[ServiceError(403), "success"])
        with patch.object(hooks.time, "sleep") as sleep:
            self.assertEqual(hooks.retry_azure(operation, "Cosmos"), "success")
            sleep.assert_called_once_with(5)
        self.assertIn("authorization/RBAC propagation", sys.stdout.getvalue())

    def test_permanent_and_unknown_errors_are_not_retried(self):
        for error in (ServiceError(400), ServiceError(404), ValueError("bad seed"), RuntimeError("bad command")):
            with self.subTest(error=error), patch.object(hooks.time, "sleep") as sleep:
                with self.assertRaises(type(error)):
                    hooks.retry_azure(Mock(side_effect=error), "Seed")
                sleep.assert_not_called()

    def test_retry_is_bounded(self):
        operation = Mock(side_effect=ServiceError(429))
        with patch.object(hooks.time, "sleep") as sleep:
            with self.assertRaises(ServiceError):
                hooks.retry_azure(operation, "Search", attempts=3, delay=1)
            self.assertEqual(operation.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_async_project_rbac_retry_preserves_status_classification(self):
        operation = AsyncMock(side_effect=[ServiceError(403), "ready"])
        with patch.object(hooks.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            self.assertEqual(asyncio.run(hooks.retry_azure_async(operation, "Foundry")), "ready")
            sleep.assert_awaited_once_with(5)
        operation = AsyncMock(side_effect=ValueError("invalid configuration"))
        with self.assertRaises(ValueError):
            asyncio.run(hooks.retry_azure_async(operation, "Foundry"))
        self.assertEqual(operation.await_count, 1)


class SeedTests(QuietTest):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.dict(os.environ, {"GSDR_AZD_HOOK": "1", "COSMOS_ENDPOINT": "https://cosmos.example"}, clear=True))
        self.client = MagicMock()
        self.client.__enter__.return_value = self.client
        credential = MagicMock()
        self.modules = {
            "azure": module("azure"),
            "azure.cosmos": module("azure.cosmos", CosmosClient=Mock(return_value=self.client)),
            "azure.identity": module("azure.identity", DefaultAzureCredential=Mock(return_value=credential)),
        }
        self.enterContext(patch.dict(sys.modules, self.modules))
        self.database = self.client.get_database_client.return_value
        self.container = self.database.get_container_client.return_value
        self.container.read.return_value = {"partitionKey": {"paths": ["/partitionKey"]}}
        self.enterContext(patch.object(seed, "CONTAINER_FILES", {"products": "products.json"}))

    def test_existing_cosmos_resources_are_read_and_upserted_not_created(self):
        seed.seed_cosmos()
        self.client.create_database_if_not_exists.assert_not_called()
        self.database.create_container_if_not_exists.assert_not_called()
        self.database.read.assert_called_once()
        self.container.read.assert_called_once()
        self.assertGreater(self.container.upsert_item.call_count, 0)

    def test_cosmos_upsert_errors_propagate(self):
        self.container.upsert_item.side_effect = ServiceError(400)
        with self.assertRaises(ServiceError):
            seed.seed_cosmos()
        self.client.__exit__.assert_called_once()

    def test_partition_mismatch_fails_before_upserts(self):
        self.container.read.return_value = {"partitionKey": {"paths": ["/wrong"]}}
        with self.assertRaisesRegex(ValueError, "partitionKey"):
            seed.seed_cosmos()
        self.container.upsert_item.assert_not_called()

    def test_missing_seed_file_fails(self):
        with patch.object(seed, "CONTAINER_FILES", {"products": "not-present.json"}):
            with self.assertRaises(FileNotFoundError):
                seed.seed_cosmos()

    def test_missing_seed_config_is_not_a_successful_skip(self):
        with patch.dict(os.environ, {"GSDR_AZD_HOOK": "1"}, clear=True):
            with self.assertRaisesRegex(ValueError, "COSMOS_ENDPOINT"):
                seed.main(["cosmos"])

    def test_main_propagates_seed_failure(self):
        with patch.object(seed, "seed_cosmos", side_effect=RuntimeError("seeding failed")):
            with self.assertRaisesRegex(RuntimeError, "seeding failed"):
                seed.main(["cosmos"])

    def test_unknown_seed_target_fails(self):
        with self.assertRaises(SystemExit) as error:
            seed.main(["unexpected"])
        self.assertEqual(error.exception.code, 2)

    @staticmethod
    def result(key, success, status):
        return SimpleNamespace(key=key, succeeded=success, status_code=status, error_message="upload error")

    def test_search_partial_failure_is_fatal(self):
        client = Mock()
        client.upload_documents.return_value = [self.result("a", True, 200), self.result("b", False, 400)]
        with patch.object(hooks.time, "sleep") as sleep:
            with self.assertRaisesRegex(seed.SearchUploadError, "b: HTTP 400"):
                seed.upload_search_documents(client, [{"id": "a"}, {"id": "b"}])
            sleep.assert_not_called()

    def test_search_transient_partial_failure_retries_only_failed_documents(self):
        client = Mock()
        client.upload_documents.side_effect = [
            [self.result("a", True, 200), self.result("b", False, 503)],
            [self.result("b", True, 200)],
        ]
        with patch.object(hooks.time, "sleep"):
            seed.upload_search_documents(client, [{"id": "a"}, {"id": "b"}])
        self.assertEqual(client.upload_documents.call_args.kwargs["documents"], [{"id": "b"}])

    def test_missing_search_results_fail(self):
        client = Mock()
        client.upload_documents.return_value = [self.result("a", True, 200)]
        with self.assertRaisesRegex(RuntimeError, "every document"):
            seed.upload_search_documents(client, [{"id": "a"}, {"id": "b"}])


class FoundryTests(QuietTest):
    def setUp(self):
        super().setUp()
        self.close = AsyncMock()
        self.provision = AsyncMock(return_value={"enabled": True, "agents": [], "errors": {}})
        self.settings = SimpleNamespace(ai_project_endpoint="https://project.example", model_deployment="model")
        self.enterContext(patch.dict(sys.modules, {
            "app.agents.foundry": module("app.agents.foundry", close=self.close, provision_all=self.provision),
            "app.config": module("app.config", get_settings=lambda: self.settings),
        }))
        self.script = importlib.import_module("scripts.provision_agents")
        self.enterContext(patch.dict(os.environ, {}, clear=True))

    def test_provision_errors_return_nonzero_and_close(self):
        self.provision.return_value["errors"] = {"agent": "Forbidden"}
        self.assertEqual(asyncio.run(self.script.main()), 2)
        self.close.assert_awaited_once()

    def test_provision_exception_closes_and_propagates(self):
        self.provision.side_effect = RuntimeError("service error")
        with self.assertRaisesRegex(RuntimeError, "service error"):
            asyncio.run(self.script.main())
        self.close.assert_awaited_once()

    def test_empty_or_disabled_provisioning_is_not_success(self):
        self.assertEqual(asyncio.run(self.script.main()), 1)

    def test_missing_project_fails_without_provisioning(self):
        self.settings.ai_project_endpoint = ""
        self.assertEqual(asyncio.run(self.script.main()), 1)
        self.provision.assert_not_awaited()

    def test_hook_checks_project_access_before_provisioning(self):
        with patch.dict(os.environ, {"GSDR_AZD_HOOK": "1"}):
            with patch.object(self.script, "wait_for_project_access", new_callable=AsyncMock) as access:
                access.side_effect = ServiceError(400)
                with self.assertRaises(ServiceError):
                    asyncio.run(self.script.main())
                self.provision.assert_not_awaited()
                self.close.assert_awaited_once()

    def test_project_probe_waits_for_rbac_and_accepts_new_agent(self):
        async def items(values):
            for item in values:
                yield item

        class NotFound(Exception):
            pass

        hosted = object()
        client = MagicMock()
        client.__aenter__.return_value = client
        client.connections.list.side_effect = [
            ServiceError(403),
            items([SimpleNamespace(name="knowledge-search", type="azure-ai-search")]),
        ]
        client.agents.list_versions.side_effect = NotFound()
        credential = MagicMock()
        modules = {
            "azure.ai.projects.aio": module("azure.ai.projects.aio", AIProjectClient=Mock(return_value=client)),
            "azure.core.exceptions": module("azure.core.exceptions", ResourceNotFoundError=NotFound),
            "azure.identity.aio": module("azure.identity.aio", DefaultAzureCredential=Mock(return_value=credential)),
            "app.agents.definitions": module("app.agents.definitions", AGENTS=[SimpleNamespace(hosting_mode=hosted)]),
            "app.contracts": module("app.contracts", HostingMode=SimpleNamespace(FOUNDRY=hosted)),
            "app.agents.foundry": module("app.agents.foundry", agent_name_for=lambda _: "agent"),
        }
        self.settings.enable_foundry_knowledge = True
        self.settings.knowledge_connection_name = "knowledge-search"
        with patch.dict(sys.modules, modules), patch.object(hooks.asyncio, "sleep", new_callable=AsyncMock):
            asyncio.run(self.script.wait_for_project_access(self.settings))
        self.assertEqual(client.connections.list.call_count, 2)
        client.__aexit__.assert_awaited_once()


class SmokeTests(QuietTest):
    def setUp(self):
        super().setUp()
        self.now = 0
        self.enterContext(patch.object(hooks.time, "monotonic", side_effect=lambda: self.now))
        self.sleep = self.enterContext(patch.object(hooks.time, "sleep", side_effect=self.advance))
        self.open = self.enterContext(patch.object(hooks, "urlopen"))
        self.health = {
            "status": "healthy", "openAiConfigured": True, "dataSource": "cosmos",
            "knowledgeSource": "azure-ai-search", "model": "model", "agentCount": 10,
        }
        self.scenario = {
            "signal": {"id": "INC-1"},
            "graph": {"nodes": [{"id": "agent"}], "edges": [{"from": "start", "to": "agent"}]},
            "agents": [{"nodeId": "agent", "name": "Agent"}],
        }

    def advance(self, seconds):
        self.now += seconds

    @staticmethod
    def response(content, content_type):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers = {"Content-Type": content_type}
        response.read.return_value = content.encode()
        return response

    def responses(self):
        return [
            self.response(
                '<html><title>Grocery Supply Disruption Response</title><div id="root"></div>'
                '<script type="module" src="/assets/index-1.js"></script></html>', "text/html",
            ),
            self.response("console.log('app');", "application/javascript"),
            self.response(json.dumps(self.health), "application/json"),
            self.response(json.dumps(self.scenario), "application/json"),
        ]

    def test_frontend_asset_health_and_scenario_checked_without_workflow(self):
        self.open.side_effect = self.responses()
        hooks.verify_application("https://app.example")
        paths = [call.args[0] for call in self.open.call_args_list]
        self.assertEqual(paths, [
            "https://app.example/", "https://app.example/assets/index-1.js",
            "https://app.example/api/health", "https://app.example/api/scenario",
        ])
        self.assertTrue(all(0 < call.kwargs["timeout"] <= 15 for call in self.open.call_args_list))

    def test_frontend_backend_fallback_is_rejected(self):
        self.open.return_value = self.response('{"message":"API only"}', "application/json")
        with self.assertRaisesRegex(hooks.VerificationError, "Frontend"):
            hooks.verify_application("https://app.example", timeout=1, interval=1)

    def test_missing_bundle_is_rejected(self):
        replies = self.responses()
        replies[1] = self.response("<html>fallback</html>", "text/html")
        self.open.side_effect = replies
        with self.assertRaisesRegex(hooks.VerificationError, "JavaScript"):
            hooks.verify_application("https://app.example", timeout=1, interval=1)

    def test_local_data_fallback_is_rejected(self):
        self.health["dataSource"] = "local-seed"
        self.open.side_effect = self.responses()
        with self.assertRaisesRegex(hooks.VerificationError, "dataSource"):
            hooks.verify_application("https://app.example", timeout=1, interval=1)

    def test_missing_scenario_data_is_rejected(self):
        self.scenario["signal"] = {}
        self.open.side_effect = self.responses()
        with self.assertRaisesRegex(hooks.VerificationError, "seeded signal"):
            hooks.verify_application("https://app.example", timeout=1, interval=1)

    def test_transient_service_error_polls_then_succeeds(self):
        self.open.side_effect = [HTTPError("https://app.example", 503, "unavailable", {}, None), *self.responses()]
        hooks.verify_application("https://app.example", timeout=10, interval=1)
        self.sleep.assert_called_once_with(1)

    def test_authorization_error_is_not_blindly_retried(self):
        self.open.side_effect = HTTPError("https://app.example", 401, "unauthorized", {}, None)
        with self.assertRaises(HTTPError):
            hooks.verify_application("https://app.example")
        self.sleep.assert_not_called()

    def test_missing_url_fails_and_service_url_fallback_is_supported(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(hooks.main(["--phase", "postdeploy"]), 1)
        self.open.side_effect = self.responses()
        with patch.dict(os.environ, {"SERVICE_APP_ENDPOINT_URL": "https://app.example"}, clear=True):
            self.assertEqual(hooks.main(["--phase", "postdeploy"]), 0)


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is not installed")
class PowerShellTests(unittest.TestCase):
    def test_wrapper_propagates_python_failure(self):
        env = dict(os.environ)
        env.pop("APP_URL", None)
        env.pop("SERVICE_APP_ENDPOINT_URL", None)
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(ROOT / "scripts" / "azd-hooks.ps1"), "-Phase", "postdeploy"],
            env=env, cwd=ROOT, text=True, capture_output=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing azd output", result.stderr)


if __name__ == "__main__":
    unittest.main()
