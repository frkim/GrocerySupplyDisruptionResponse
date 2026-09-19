"""Validate deployment authentication offline, using only fake credentials and CLI stubs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
CLIENT = "abcdef12-1234-4567-890a-abcdef123456"
TENANT = "bcdef123-2345-4678-901b-bcdef1234567"
SUBSCRIPTION = "cdef1234-3456-4789-012c-cdef12345678"
OTHER_ID = "def12345-4567-4890-123d-def123456789"
SECRET = "fake-client-secret-NEVER-PRINT"
TOKEN = "fake-cli-token-NEVER-PRINT"
VARIABLES = {
    "AZURE_CLIENT_ID": CLIENT,
    "AZURE_TENANT_ID": TENANT,
    "AZURE_SUBSCRIPTION_ID": SUBSCRIPTION,
    "AZURE_ENV_NAME": "test-environment",
    "AZURE_LOCATION": "swedencentral",
}
CREDENTIALS = {
    "clientId": CLIENT,
    "tenantId": TENANT,
    "subscriptionId": SUBSCRIPTION,
    "clientSecret": SECRET,
}
ACCOUNT = {
    "id": SUBSCRIPTION,
    "tenantId": TENANT,
    "user": {"name": CLIENT, "type": "servicePrincipal"},
}
EXPECTED_CALLS = [
    ["az", "account", "show", "--output", "json", "--only-show-errors"],
    ["azd", "config", "set", "auth.useAzCliAuth", "true"],
    ["azd", "auth", "login", "--check-status"],
]
TRACE_PREFIX = "AUTH_TEST_TRACE:"

HARNESS = r"""
$ErrorActionPreference = 'Stop'
$global:LASTEXITCODE = 0
$case = $env:TEST_AUTH_CASE | ConvertFrom-Json -AsHashtable
$calls = [System.Collections.Generic.List[object]]::new()
$before = [Environment]::GetEnvironmentVariables()
function Invoke-Stub {
    param([string]$Command, [object[]]$Arguments)
    $calls.Add(@($Command) + @($Arguments))
    $stage = if ($Command -eq 'az') { 'account' } else { $Arguments[0] }
    $response = $case['responses'][$stage]
    if (-not $response) { throw 'Unexpected CLI command.' }
    $global:LASTEXITCODE = $response['exitCode']
    if ($response['stdout']) { $response['stdout'] -split "`n" }
    if ($response['stderr']) { Write-Error $response['stderr'] -ErrorAction Continue }
    if ($response['exception']) { throw $response['exception'] }
}
function az { Invoke-Stub -Command 'az' -Arguments $args }
function azd { Invoke-Stub -Command 'azd' -Arguments $args }
try {
    $parameters = $case['parameters']
    & $env:TEST_AUTH_SCRIPT @parameters
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
finally {
    $after = [Environment]::GetEnvironmentVariables()
    $changed = @(
        foreach ($name in @($before.Keys) + @($after.Keys) | Select-Object -Unique) {
            if ($before[$name] -cne $after[$name]) { $name }
        }
    )
    $trace = @{ calls = @($calls.ToArray()); changedEnvironment = $changed } |
        ConvertTo-Json -Depth 10 -Compress
    [Console]::Out.WriteLine('AUTH_TEST_TRACE:' + $trace)
}
"""


@unittest.skipUnless(PWSH, "PowerShell 7 is required for script execution tests")
class AzureAuthTests(unittest.TestCase):
    def run_auth(self, mode="ValidateSecret", *, payload=None, environment=None, responses=None):
        case = {
            "parameters": {} if mode is None else {"Mode": mode},
            "responses": {
                "account": {"stdout": json.dumps(ACCOUNT, indent=2), "exitCode": 0},
                "config": {"stdout": TOKEN, "exitCode": 0},
                "auth": {"stdout": TOKEN, "exitCode": 0},
            },
        }
        case["responses"].update(responses or {})
        # Do not propagate workstation/cloud-runner credentials into the child process.
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith(
                ("AZURE_", "AZD_", "ARM_", "GITHUB_", "ACTIONS_", "TEST_AUTH_")
            )
        }
        env.update(VARIABLES)
        if mode == "ValidateSecret":
            env["AZURE_CREDENTIALS"] = json.dumps(CREDENTIALS) if payload is None else payload
        for key, value in (environment or {}).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        env.update(
            TEST_AUTH_CASE=json.dumps(case),
            TEST_AUTH_SCRIPT=str(ROOT / "scripts" / "configure-azure-auth.ps1"),
        )
        result = subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", HARNESS],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        for value in (SECRET, TOKEN, CLIENT, TENANT, SUBSCRIPTION, OTHER_ID):
            self.assertNotIn(value.lower(), result.stdout.lower())
            self.assertNotIn(value.lower(), result.stderr.lower())
        trace_lines = [line for line in result.stdout.splitlines() if line.startswith(TRACE_PREFIX)]
        self.assertEqual(len(trace_lines), 1, result.stderr)
        trace = json.loads(trace_lines[0][len(TRACE_PREFIX):])
        self.assertEqual(trace["changedEnvironment"], [])
        return result, trace["calls"]

    def assert_failure(self, result, expected):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(expected, result.stderr)
        self.assertNotIn("\x1b[", result.stderr)
        self.assertNotIn("is valid and matches", result.stdout)
        self.assertNotIn("service principal verified", result.stdout)

    def test_valid_secret_is_checked_without_cli_or_environment_writes(self):
        result, calls = self.run_auth()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AZURE_CREDENTIALS is valid and matches", result.stdout)
        self.assertEqual(calls, [])

    def test_guid_matching_uses_guid_semantics_not_string_case(self):
        credentials = {
            **CREDENTIALS,
            **{key: "{" + CREDENTIALS[key].upper() + "}" for key in (
                "clientId", "tenantId", "subscriptionId"
            )},
        }
        result, calls = self.run_auth(payload=json.dumps(credentials))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])
        result, calls = self.run_auth("UseAzureCli", environment={
            key: value.upper().replace("-", "") for key, value in VARIABLES.items()
            if key.endswith("_ID")
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, EXPECTED_CALLS)

    def test_mode_is_mandatory_and_restricted(self):
        for mode in (None, "Other"):
            with self.subTest(mode=mode):
                result, calls = self.run_auth(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])

    def test_all_repository_variables_are_required_in_both_modes(self):
        for mode in ("ValidateSecret", "UseAzureCli"):
            for name in VARIABLES:
                for value in (None, "", " \t\n "):
                    with self.subTest(mode=mode, variable=name, value=value):
                        result, calls = self.run_auth(mode, environment={name: value})
                        self.assert_failure(result, name)
                        self.assertEqual(calls, [])

    def test_repository_ids_must_be_guids_in_both_modes(self):
        for mode in ("ValidateSecret", "UseAzureCli"):
            for name in ("AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID"):
                for value in ("not-a-guid", "00000000-0000-0000-0000-000000000000"):
                    with self.subTest(mode=mode, variable=name, value=value):
                        result, calls = self.run_auth(mode, environment={name: value})
                        self.assert_failure(result, f"{name} must be a nonempty, valid GUID")
                        self.assertEqual(calls, [])

    def test_secret_must_be_present_and_an_object(self):
        for payload in (
            "", " \n ", "null", "[]", json.dumps([CREDENTIALS]), json.dumps(SECRET),
            "true", "123", '{"clientSecret":"' + SECRET + '",invalid}',
            '{"clientSecret":"' + SECRET,
        ):
            with self.subTest(payload_type="invalid JSON or shape"):
                result, calls = self.run_auth(payload=payload)
                self.assert_failure(result, "AZURE_CREDENTIALS")
                self.assertEqual(calls, [])
        result, calls = self.run_auth(environment={"AZURE_CREDENTIALS": None})
        self.assert_failure(result, "AZURE_CREDENTIALS is missing or empty")
        self.assertEqual(calls, [])

    def test_all_secret_fields_require_nonempty_strings(self):
        for field in CREDENTIALS:
            for value in (None, "", " \t ", 123, True, [], [SECRET], {"nested": SECRET}):
                with self.subTest(field=field, value_type=type(value).__name__):
                    result, calls = self.run_auth(payload=json.dumps({**CREDENTIALS, field: value}))
                    self.assert_failure(result, f"nonempty string for {field}")
                    self.assertEqual(calls, [])
            with self.subTest(field=field, missing=True):
                result, calls = self.run_auth(payload=json.dumps({
                    key: value for key, value in CREDENTIALS.items() if key != field
                }))
                self.assert_failure(result, f"nonempty string for {field}")
                self.assertEqual(calls, [])

    def test_secret_ids_must_be_valid_and_match_repository_variables(self):
        for field in ("clientId", "tenantId", "subscriptionId"):
            for value in ("not-a-guid", "00000000-0000-0000-0000-000000000000", OTHER_ID):
                with self.subTest(field=field, value=value):
                    result, calls = self.run_auth(payload=json.dumps({**CREDENTIALS, field: value}))
                    expected = "does not match repository variable" if value == OTHER_ID else "valid GUID"
                    self.assert_failure(result, expected)
                    self.assertEqual(calls, [])

    def test_cli_flow_does_not_require_or_validate_the_secret(self):
        for secret in (None, SECRET, "null"):
            with self.subTest(secret_present=secret is not None):
                result, calls = self.run_auth("UseAzureCli", environment={"AZURE_CREDENTIALS": secret})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("service principal verified", result.stdout)
                self.assertEqual(calls, EXPECTED_CALLS)

    def test_native_failures_stop_at_the_failed_command_without_leaking_output(self):
        for index, stage in enumerate(("account", "config", "auth"), 1):
            with self.subTest(stage=stage):
                result, calls = self.run_auth("UseAzureCli", responses={
                    stage: {
                        "stdout": json.dumps({**ACCOUNT, "accessToken": TOKEN}),
                        "stderr": TOKEN,
                        "exitCode": 7,
                    }
                })
                self.assert_failure(result, "failed (exit 7)")
                self.assertEqual(calls, EXPECTED_CALLS[:index])

    def test_cli_invocation_exceptions_are_sanitized(self):
        for index, stage in enumerate(("account", "config", "auth"), 1):
            with self.subTest(stage=stage):
                result, calls = self.run_auth("UseAzureCli", responses={
                    stage: {"exception": TOKEN, "exitCode": 0}
                })
                self.assert_failure(result, "failed. Deployment is blocked")
                self.assertEqual(calls, EXPECTED_CALLS[:index])

    def test_account_response_must_be_valid_json_object(self):
        for output in ("", " \n ", "null", "[]", json.dumps([ACCOUNT]), "true", "123",
                       json.dumps(TOKEN), '{"accessToken":"' + TOKEN + '",invalid}'):
            with self.subTest(output_type="invalid JSON or shape"):
                result, calls = self.run_auth("UseAzureCli", responses={
                    "account": {"stdout": output, "exitCode": 0}
                })
                self.assert_failure(result, "Azure CLI account response")
                self.assertEqual(calls, EXPECTED_CALLS[:1])

    def test_account_ids_must_be_valid_and_match_repository_variables(self):
        for field, variable in (("id", "AZURE_SUBSCRIPTION_ID"), ("tenantId", "AZURE_TENANT_ID")):
            for value in (None, "", " ", True, 123, [SUBSCRIPTION], {"id": SUBSCRIPTION},
                          "not-a-guid", "00000000-0000-0000-0000-000000000000", OTHER_ID):
                with self.subTest(field=field, value_type=type(value).__name__):
                    result, calls = self.run_auth("UseAzureCli", responses={
                        "account": {"stdout": json.dumps({**ACCOUNT, field: value}), "exitCode": 0}
                    })
                    self.assert_failure(result, variable if value == OTHER_ID else "valid GUID")
                    self.assertEqual(calls, EXPECTED_CALLS[:1])
            result, calls = self.run_auth("UseAzureCli", responses={
                "account": {
                    "stdout": json.dumps({key: value for key, value in ACCOUNT.items() if key != field}),
                    "exitCode": 0,
                }
            })
            self.assert_failure(result, "valid GUID")
            self.assertEqual(calls, EXPECTED_CALLS[:1])

    def test_account_user_must_be_the_service_principal(self):
        for user in (
            None, [], [ACCOUNT["user"]], "servicePrincipal", {},
            {"name": CLIENT}, {"name": CLIENT, "type": None},
            {"name": CLIENT, "type": ["servicePrincipal"]},
            {"name": CLIENT, "type": 123}, {"name": CLIENT, "type": True},
            {"name": CLIENT, "type": "user"}, {"name": CLIENT, "type": "managedIdentity"},
            {"name": CLIENT, "type": "ServicePrincipal"},
        ):
            with self.subTest(user_type=type(user).__name__):
                result, calls = self.run_auth("UseAzureCli", responses={
                    "account": {"stdout": json.dumps({**ACCOUNT, "user": user}), "exitCode": 0}
                })
                self.assert_failure(result, "must be authenticated as the deployment service principal")
                self.assertEqual(calls, EXPECTED_CALLS[:1])
        for name in (None, "", " ", True, 123, [CLIENT], {"name": CLIENT}, "not-a-guid",
                     "00000000-0000-0000-0000-000000000000", OTHER_ID):
            with self.subTest(name_type=type(name).__name__):
                result, calls = self.run_auth("UseAzureCli", responses={
                    "account": {
                        "stdout": json.dumps({**ACCOUNT, "user": {"type": "servicePrincipal", "name": name}}),
                        "exitCode": 0,
                    }
                })
                self.assert_failure(result, "AZURE_CLIENT_ID" if name == OTHER_ID else "valid GUID")
                self.assertEqual(calls, EXPECTED_CALLS[:1])

    def test_account_user_and_name_cannot_be_missing(self):
        for account, expected in (
            ({"id": SUBSCRIPTION, "tenantId": TENANT}, "deployment service principal"),
            ({**ACCOUNT, "user": {"type": "servicePrincipal"}}, "valid GUID"),
        ):
            with self.subTest(expected=expected):
                result, calls = self.run_auth("UseAzureCli", responses={
                    "account": {"stdout": json.dumps(account), "exitCode": 0}
                })
                self.assert_failure(result, expected)
                self.assertEqual(calls, EXPECTED_CALLS[:1])


if __name__ == "__main__":
    unittest.main()
