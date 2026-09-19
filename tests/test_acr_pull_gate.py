"""Exercise the pre-deploy RBAC gate offline; no Azure credentials are used."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
SUBSCRIPTION = "11111111-1111-1111-1111-111111111111"
PRINCIPAL = "22222222-2222-2222-2222-222222222222"
GROUP = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-test"
IDENTITY = f"{GROUP}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/runtime"
REGISTRY = f"{GROUP}/providers/Microsoft.ContainerRegistry/registries/testregistry"
ROLE = "7f951dda-4ed3-4680-a7ca-43fe172d538d"

HARNESS = r"""
$ErrorActionPreference = 'Stop'
$global:LASTEXITCODE = 0
$case = Get-Content -LiteralPath $env:TEST_CASE_FILE -Raw | ConvertFrom-Json -AsHashtable
$calls = [System.Collections.Generic.List[object]]::new()
$sleeps = [System.Collections.Generic.List[int]]::new()
$counts = @{}
function az {
    $calls.Add(@($args))
    $stage = $args[0]
    if (-not $counts.ContainsKey($stage)) { $counts[$stage] = 0 }
    $responses = $case['responses'][$stage]
    if (-not $responses) { throw "Unexpected Azure CLI command: $args" }
    $index = [Math]::Min($counts[$stage], $responses.Count - 1)
    $counts[$stage]++
    $response = $responses[$index]
    $global:LASTEXITCODE = $response['exitCode']
    if ($response['stdout']) { $response['stdout'] -split "`n" }
}
function Start-Sleep {
    param([int]$Milliseconds)
    $sleeps.Add($Milliseconds)
}
try {
    $parameters = $case['parameters']
    & $env:TEST_GATE_SCRIPT @parameters
}
finally {
    @{ calls = @($calls.ToArray()); sleeps = @($sleeps.ToArray()) } |
        ConvertTo-Json -Depth 10 | Set-Content -LiteralPath trace.json
}
"""


def assignment(**overrides):
    return {
        "principalId": PRINCIPAL,
        "scope": REGISTRY,
        "roleDefinitionId": (
            f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Authorization/roleDefinitions/{ROLE}"
        ),
        **overrides,
    }


@unittest.skipUnless(PWSH, "PowerShell 7 is required for script execution tests")
class AcrPullGateTests(unittest.TestCase):
    def run_gate(self, *, responses=None, parameters=None):
        case = {
            "responses": {
                "account": [{"stdout": SUBSCRIPTION, "exitCode": 0}],
                "identity": [{"stdout": PRINCIPAL, "exitCode": 0}],
                "acr": [{"stdout": REGISTRY, "exitCode": 0}],
                "role": [{"stdout": json.dumps([assignment()], indent=2), "exitCode": 0}],
            },
            "parameters": {
                "IdentityResourceId": IDENTITY,
                "RegistryName": "testregistry",
                "ResourceGroup": "rg-test",
                "SubscriptionId": SUBSCRIPTION,
                "RetryCount": 3,
                "RetryIntervalSeconds": 0,
            },
        }
        case["responses"].update(responses or {})
        case["parameters"].update(parameters or {})
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".acr-gate-test-") as directory:
            root = Path(directory)
            (root / "case.json").write_text(json.dumps(case), encoding="utf-8")
            (root / "harness.ps1").write_text(HARNESS, encoding="utf-8")
            environment = dict(
                os.environ,
                TEST_CASE_FILE=str(root / "case.json"),
                TEST_GATE_SCRIPT=str(ROOT / "scripts" / "verify-acr-pull.ps1"),
            )
            result = subprocess.run(
                [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(root / "harness.ps1")],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            trace = json.loads((root / "trace.json").read_text(encoding="utf-8-sig"))
            return result, trace["calls"], trace["sleeps"]

    def test_visible_assignment_succeeds_without_graph_or_writes(self):
        result, calls, sleeps = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AcrPull role is visible", result.stdout)
        self.assertEqual([call[0] for call in calls], ["account", "identity", "acr", "role"])
        self.assertEqual(sleeps, [])
        self.assertEqual(calls[1][calls[1].index("--ids") + 1], IDENTITY)
        for call in calls[1:]:
            self.assertEqual(call[call.index("--subscription") + 1], SUBSCRIPTION)
        role_call = calls[-1]
        self.assertEqual(role_call[:3], ["role", "assignment", "list"])
        for flag, value in (
            ("--assignee-object-id", PRINCIPAL),
            ("--scope", REGISTRY),
            ("--fill-principal-name", "false"),
            ("--fill-role-definition-name", "false"),
        ):
            self.assertEqual(role_call[role_call.index(flag) + 1], value)
        self.assertNotIn("--assignee", role_call)
        self.assertNotIn("--include-groups", role_call)

    def test_missing_role_retries_then_succeeds(self):
        result, calls, sleeps = self.run_gate(responses={"role": [
            {"stdout": "[]", "exitCode": 0},
            {"stdout": "[]", "exitCode": 0},
            {"stdout": json.dumps([assignment()]), "exitCode": 0},
        ]})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(call[0] == "role" for call in calls), 3)
        self.assertEqual(sleeps, [0, 0])
        self.assertIn("not yet visible (attempt 1/3)", result.stdout)
        self.assertIn("Image deployment may proceed", result.stdout)

    def test_missing_role_fails_after_exact_retry_limit_without_final_sleep(self):
        result, calls, sleeps = self.run_gate(
            responses={"role": [{"stdout": "[]", "exitCode": 0}]}
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sum(call[0] == "role" for call in calls), 3)
        self.assertEqual(sleeps, [0, 0])
        self.assertIn("after 3 attempts", result.stderr)
        self.assertIn("Deployment is blocked", result.stderr)
        self.assertNotIn("Image deployment may proceed", result.stdout)

    def test_native_errors_fail_immediately_even_when_output_looks_valid(self):
        valid_output = {
            "account": SUBSCRIPTION,
            "identity": PRINCIPAL,
            "acr": REGISTRY,
            "role": json.dumps([assignment()]),
        }
        for count, (stage, output) in enumerate(valid_output.items(), 1):
            with self.subTest(stage=stage):
                result, calls, sleeps = self.run_gate(
                    responses={stage: [{"stdout": output, "exitCode": 7}]}
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Azure CLI failed (exit 7)", result.stderr)
                self.assertEqual(len(calls), count)
                self.assertEqual(sleeps, [])

    def test_missing_cli_outputs_fail_without_retry(self):
        for stage in ("account", "identity", "acr", "role"):
            for output in ("", " \n ", "null"):
                with self.subTest(stage=stage, output=output):
                    result, _, sleeps = self.run_gate(
                        responses={stage: [{"stdout": output, "exitCode": 0}]}
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("returned missing output", result.stderr)
                    self.assertEqual(sleeps, [])

    def test_malformed_role_output_fails_closed(self):
        for output in ("not JSON", "{}", "[null]", '"AcrPull"'):
            with self.subTest(output=output):
                result, calls, sleeps = self.run_gate(
                    responses={"role": [{"stdout": output, "exitCode": 0}]}
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(calls), 4)
                self.assertEqual(sleeps, [])

    def test_wrong_role_principal_or_scope_does_not_pass(self):
        for override in (
            {"roleDefinitionId": "not-acrpull", "roleDefinitionName": "AcrPull"},
            {"principalId": "33333333-3333-3333-3333-333333333333"},
            {"scope": GROUP},
            {"scope": f"{REGISTRY}/repositories/app"},
        ):
            with self.subTest(override=override):
                result, _, sleeps = self.run_gate(
                    responses={"role": [{"stdout": json.dumps([assignment(**override)]), "exitCode": 0}]},
                    parameters={"RetryCount": 1},
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("AcrPull is not visible", result.stderr)
                self.assertEqual(sleeps, [])

    def test_subscription_mismatch_stops_before_resource_queries(self):
        result, calls, _ = self.run_gate(
            responses={"account": [{"stdout": "33333333-3333-3333-3333-333333333333", "exitCode": 0}]}
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match deployment subscription", result.stderr)
        self.assertEqual(len(calls), 1)

    def test_identity_must_be_user_assigned_in_target_subscription(self):
        for identity in (REGISTRY, IDENTITY.replace(SUBSCRIPTION, PRINCIPAL)):
            with self.subTest(identity=identity):
                result, calls, _ = self.run_gate(parameters={"IdentityResourceId": identity})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("user-assigned identity resource ID", result.stderr)
                self.assertEqual(len(calls), 1)

    def test_invalid_principal_and_unexpected_registry_fail_closed(self):
        for stage, output, expected in (
            ("identity", "not-a-guid", "invalid principal ID"),
            ("identity", "00000000-0000-0000-0000-000000000000", "invalid principal ID"),
            ("acr", f"{REGISTRY}-other", "does not match expected deployment registry"),
        ):
            with self.subTest(stage=stage, output=output):
                result, calls, _ = self.run_gate(
                    responses={stage: [{"stdout": output, "exitCode": 0}]}
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                self.assertNotIn("role", [call[0] for call in calls])

    def test_empty_resource_inputs_fail_before_cli(self):
        for name in ("IdentityResourceId", "RegistryName", "ResourceGroup"):
            with self.subTest(name=name):
                result, calls, _ = self.run_gate(parameters={name: ""})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])

    def test_retry_parameters_cannot_remove_attempt_bound(self):
        for parameters in ({"RetryCount": 0}, {"RetryCount": 32}, {"RetryIntervalSeconds": -1}):
            with self.subTest(parameters=parameters):
                result, calls, _ = self.run_gate(parameters=parameters)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
