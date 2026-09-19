"""Offline regression checks for the deployment entry points."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")


class DeploymentContractTests(unittest.TestCase):
    def test_azd_uses_remote_docker_build_and_all_hooks(self):
        config = (ROOT / "azure.yaml").read_text(encoding="utf-8")
        for setting in ("host: containerapp", "remoteBuild: true", "context: ."):
            self.assertIn(setting, config)
        self.assertIn("module: app", config)
        self.assertIn("resourceName: ${AZURE_CONTAINER_APP_NAME}", config)
        parameters = json.loads((ROOT / "infra/app.parameters.json").read_text(encoding="utf-8"))
        self.assertEqual(
            parameters["parameters"]["containerImage"]["value"], "${SERVICE_APP_IMAGE_NAME}"
        )
        main = (ROOT / "infra/main.bicep").read_text(encoding="utf-8")
        self.assertNotIn("module app ", main)
        self.assertNotIn("resource containerApp ", main)
        for phase in ("preprovision", "postprovision", "postdeploy"):
            self.assertIn(f"./scripts/azd-hooks.ps1 -Phase {phase}", config)

    def test_pipeline_uses_repository_credentials_and_is_gated_on_ci(self):
        workflow = (ROOT / ".github/workflows/azure-dev.yml").read_text(encoding="utf-8")
        self.assertIn("creds: ${{ secrets.AZURE_CREDENTIALS }}", workflow)
        self.assertNotIn("--client-secret", workflow)
        self.assertNotIn("id-token: write", workflow)
        self.assertNotIn("--federated-credential-provider", workflow)
        self.assertNotIn("AZURE_CREDENTIALS", workflow.split("jobs:", 1)[0])
        self.assertIn("github.event.workflow_run.conclusion == 'success'", workflow)
        self.assertIn("github.event.workflow_run.event == 'push'", workflow)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("github.event.workflow_run.head_sha || github.sha", workflow)
        self.assertIn("uses: azure/login@v2", workflow)
        validation = workflow.index("./scripts/configure-azure-auth.ps1 -Mode ValidateSecret")
        login = workflow.index("uses: azure/login@v2")
        azd_auth = workflow.index("./scripts/configure-azure-auth.ps1 -Mode UseAzureCli")
        self.assertLess(validation, login)
        self.assertLess(login, azd_auth)
        for setting in ("client-id:", "tenant-id:", "subscription-id:"):
            self.assertNotIn(setting, workflow)
        self.assertNotIn("azd up", workflow)
        provision = workflow.index("azd provision --no-prompt --environment $env:AZURE_ENV_NAME")
        self.assertLess(azd_auth, provision)
        gate = workflow.index("./scripts/verify-acr-pull.ps1")
        deploy = workflow.index("azd deploy --no-prompt --environment $env:AZURE_ENV_NAME")
        self.assertLess(provision, gate)
        self.assertLess(gate, deploy)
        self.assertIn("timeout-minutes: 6", workflow)
        self.assertIn("azd env get-values --output json --environment $env:AZURE_ENV_NAME", workflow)
        for output in ("SERVICE_APP_IDENTITY_ID", "AZURE_CONTAINER_REGISTRY_NAME", "AZURE_RESOURCE_GROUP"):
            self.assertIn(f"$outputs['{output}']", workflow)
        self.assertFalse((ROOT / ".github/workflows/deploy.yml").exists())

    def test_parameters_are_azd_arm_json(self):
        parameters = json.loads((ROOT / "infra/main.parameters.json").read_text(encoding="utf-8"))
        values = json.dumps(parameters["parameters"])
        for setting in ("AZURE_ENV_NAME", "AZURE_LOCATION", "AZURE_PRINCIPAL_ID"):
            self.assertIn("${" + setting + "}", values)
        self.assertNotIn("bb766161", values)
        self.assertNotIn("6d84d14b", values)

    def test_cosmos_is_private_without_trusted_service_or_key_bypass(self):
        core = (ROOT / "infra/core.bicep").read_text(encoding="utf-8")
        cosmos = core.split("resource cosmos '", 1)[1].split("// Shared database", 1)[0]
        for setting in ("publicNetworkAccess: 'Disabled'", "networkAclBypass: 'None'",
                        "disableLocalAuth: true"):
            self.assertIn(setting, cosmos)
        self.assertNotIn("networkAclBypass: 'AzureServices'", core)
        self.assertIn("name: 'privatelink.documents.azure.com'", core)
        self.assertIn("privateLinkServiceId: cosmos.id", core)
        self.assertIn("'Sql'", core)
        self.assertIn("privateDnsZoneId: cosmosPrivateDns.id", core)
        self.assertIn("id: virtualNetwork.id", core)

    def test_private_endpoint_and_consumption_environment_use_separate_subnets(self):
        core = (ROOT / "infra/core.bicep").read_text(encoding="utf-8")
        self.assertIn("serviceName: 'Microsoft.App/environments'", core)
        self.assertIn("name: '${namePrefix}-env-private-v2-${suffix}'", core)
        self.assertIn("infrastructureSubnetId: virtualNetwork.properties.subnets[2].id", core)
        for subnet in ("container-apps", "private-endpoints", "container-apps-v2"):
            self.assertIn(f"name: '{subnet}'", core)
        for prefix in ("10.42.0.0/23", "10.42.2.0/24", "10.42.4.0/23"):
            self.assertIn(f"addressPrefix: '{prefix}'", core)
        self.assertIn("id: virtualNetwork.properties.subnets[1].id", core)
        self.assertIn("privateEndpointNetworkPolicies: 'Disabled'", core)
        self.assertIn("workloadProfileType: 'Consumption'", core)
        self.assertIn("internal: false", core)

    def test_blob_seeding_uses_private_connectivity_without_public_or_key_access(self):
        core = (ROOT / "infra/core.bicep").read_text(encoding="utf-8")
        storage = core.split("resource storage '", 1)[1].split("resource blobService", 1)[0]
        self.assertIn("publicNetworkAccess: 'Disabled'", storage)
        self.assertIn("allowSharedKeyAccess: false", storage)
        self.assertIn("name: 'privatelink.blob.${environment().suffixes.storage}'", core)
        self.assertIn("privateLinkServiceId: storage.id", core)
        self.assertIn("privateDnsZoneId: blobPrivateDns.id", core)
        self.assertIn("'blob'", core)

    def test_private_seed_job_uses_the_real_image_and_scoped_managed_identity(self):
        app = (ROOT / "infra/app.bicep").read_text(encoding="utf-8")
        job = app.split("resource seedJob ", 1)[1].split("output appUrl", 1)[0]
        for setting in ("name: '${appName}-seed'", "image: containerImage",
                        "environmentId: containerAppEnvironmentId", "'${identityId}': {}",
                        "identity: identityId", "triggerType: 'Manual'", "replicaRetryLimit: 0",
                        "replicaTimeout: 1800", "parallelism: 1", "'scripts.run_seed_job'"):
            self.assertIn(setting, job)
        self.assertNotIn("azd-service-name", job)
        self.assertEqual(app.count("env: serviceEnvironment"), 2)
        self.assertIn("value: 'ManagedIdentityCredential'", app)
        self.assertNotIn("name: 'PROVISION_FOUNDRY_AGENTS'", app)
        main = (ROOT / "infra/main.bicep").read_text(encoding="utf-8")
        self.assertIn("var appName = '${namePrefix}-app-v2'", main)
        self.assertIn("param appName string = '${namePrefix}-app-v2'", app)
        self.assertIn("output AZURE_SEED_JOB_NAME string = '${appName}-seed'", main)
        self.assertIn("output AZURE_SEED_JOB_NAME string = seedJob.name", app)


@unittest.skipUnless(PWSH, "PowerShell 7 is required for script execution tests")
class SetupScriptTests(unittest.TestCase):
    def run_setup(self, existing=False, failure=""):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            shutil.copy2(ROOT / "scripts/setup-azd.ps1", root / "scripts")
            if existing:
                env = root / ".azure/grocery-disruption"
                env.mkdir(parents=True)
                (env / ".env").write_text('APP_URL="https://keep.example"\n', encoding="utf-8")
            # A PowerShell function replaces only this subprocess's azd command.
            harness = root / "harness.ps1"
            harness.write_text(
                """$ErrorActionPreference = 'Stop'
$global:LASTEXITCODE = 0
$calls = [System.Collections.Generic.List[string]]::new()
function azd {
    $call = $args -join ' '
    $calls.Add($call)
    $global:LASTEXITCODE = 0
    if ($env:TEST_FAILURE -and $call.StartsWith($env:TEST_FAILURE)) {
        $global:LASTEXITCODE = 7
    }
}
try { & ./scripts/setup-azd.ps1 }
finally { ConvertTo-Json -InputObject @($calls) | Set-Content calls.json }
""",
                encoding="utf-8",
            )
            import os

            environment = dict(os.environ, TEST_FAILURE=failure)
            result = subprocess.run(
                [PWSH, "-NoProfile", "-NonInteractive", "-File", str(harness)],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            calls = json.loads((root / "calls.json").read_text(encoding="utf-8-sig"))
            preserved = (root / ".azure/grocery-disruption/.env").read_text() if existing else ""
            return result, calls, preserved

    def test_new_environment_uses_requested_subscription_tenant_and_region(self):
        result, calls, _ = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "env new grocery-disruption --subscription bb766161-890c-4a8e-9c63-981b510e4e38"
            " --location swedencentral --no-prompt",
            calls,
        )
        self.assertIn(
            "env set AZURE_TENANT_ID 6d84d14b-2ff0-4d99-9ab1-fae089687459"
            " --environment grocery-disruption",
            calls,
        )
        self.assertFalse(any(" up" in call or "pipeline config" in call for call in calls))

    def test_existing_environment_is_selected_not_reinitialized(self):
        result, calls, preserved = self.run_setup(existing=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[0], "env select grocery-disruption")
        self.assertFalse(any("env new" in call for call in calls))
        self.assertIn("https://keep.example", preserved)

    def test_creation_failure_stops_configuration(self):
        result, calls, _ = self.run_setup(failure="env new")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn("Cannot create azd environment", result.stderr)

    def test_setting_failure_stops_configuration(self):
        result, calls, _ = self.run_setup(failure="env set AZURE_SUBSCRIPTION_ID")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 2)
        self.assertIn("Cannot set AZURE_SUBSCRIPTION_ID", result.stderr)


if __name__ == "__main__":
    unittest.main()
