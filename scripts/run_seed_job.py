"""Run private deployment seeding inside the application image and VNet."""

from __future__ import annotations

import os
import subprocess
import sys
from uuid import UUID

from .deployment_hooks import require_outputs, run_native


def run() -> None:
    require_outputs()
    if os.getenv("AZURE_TOKEN_CREDENTIALS") != "ManagedIdentityCredential":
        raise RuntimeError("The seed job requires AZURE_TOKEN_CREDENTIALS=ManagedIdentityCredential.")
    try:
        if not UUID(os.environ["AZURE_CLIENT_ID"]).int:
            raise ValueError
    except (KeyError, ValueError):
        raise RuntimeError("The seed job requires the runtime UAI client ID in AZURE_CLIENT_ID.") from None
    env = dict(os.environ)
    env.update(GSDR_AZD_HOOK="1", PYTHON_DOTENV_DISABLED="1")
    for module in ("scripts.seed", "scripts.provision_agents"):
        print(f"Running {module} with the runtime managed identity.", flush=True)
        try:
            run_native([sys.executable, "-m", module], env=env)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Private seed stage {module} failed (exit {exc.returncode}).") from None


def main() -> int:
    try:
        run()
        print("Private seeding and agent provisioning completed.", flush=True)
        return 0
    except Exception as exc:
        print(f"Private seed job failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
