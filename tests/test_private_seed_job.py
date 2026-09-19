"""Offline ARM orchestration and image-runner tests; no Azure credentials are used."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, call, patch
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import deployment_hooks as hooks, run_seed_job as runner  # noqa: E402

SUBSCRIPTION = "11111111-2222-3333-4444-555555555555"
CLIENT_ID = "22222222-3333-4444-5555-666666666666"
TENANT_ID = "33333333-4444-5555-6666-777777777777"
RESOURCES = {
    "AZURE_SUBSCRIPTION_ID": SUBSCRIPTION,
    "AZURE_RESOURCE_GROUP": "rg-test",
    "AZURE_SEED_JOB_NAME": "gsdr-app-seed",
    "AZURE_CONTAINER_APP_NAME": "gsdr-app",
}
BASE = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-test/providers/Microsoft.App"
JOB = BASE + "/jobs/gsdr-app-seed"
APP = BASE + "/containerApps/gsdr-app"
NAME = "gsdr-app-seed-new123"
EXECUTION = {"name": NAME, "id": JOB + "/executions/" + NAME}
LOCATION = (
    hooks.ARM_ENDPOINT + f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.App"
    "/locations/swedencentral/operationResults/1234?api-version=2024-03-01"
)
FAKE_TOKEN = "fake-token-DO-NOT-PRINT"


def response(body=None, *, status=200, location=None):
    return status, body, location


def execution(state="Succeeded", **overrides):
    return {**EXECUTION, "properties": {"status": state}, **overrides}


def api(path):
    return path + "?api-version=2024-03-01"


class QuietTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("sys.stdout", new=io.StringIO()))
        self.enterContext(patch("sys.stderr", new=io.StringIO()))
        self.enterContext(patch.dict(os.environ, {}, clear=True))


class ResourceTests(QuietTest):
    def test_resource_ids_are_derived_only_from_validated_azd_outputs(self):
        with patch.dict(os.environ, RESOURCES):
            self.assertEqual(hooks.deployment_resource_paths(), (JOB, APP))

    def test_missing_and_malicious_resource_inputs_fail_before_authentication(self):
        for key in RESOURCES:
            for bad in ("", " ", "../other", "name/other", "name\\other", "name?x=1",
                        "name#other", "name%2fother", "https://attacker.example", "x\n"):
                with self.subTest(key=key, bad=bad), patch.dict(os.environ, {
                    **RESOURCES, key: bad, "APP_URL": "https://app.example",
                }), patch.object(hooks, "ArmClient") as client:
                    with self.assertRaises(ValueError):
                        hooks.postdeploy()
                    client.assert_not_called()
            with patch.dict(os.environ, {name: value for name, value in RESOURCES.items() if name != key}):
                with self.assertRaises(ValueError):
                    hooks.deployment_resource_paths()
        for key, bad in (
            ("AZURE_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000000"),
            ("AZURE_RESOURCE_GROUP", "group."),
            ("AZURE_RESOURCE_GROUP", "x" * 91),
            ("AZURE_CONTAINER_APP_NAME", "name_with_underscores"),
            ("AZURE_SEED_JOB_NAME", "Uppercase"),
            ("AZURE_CONTAINER_APP_NAME", "a" * 33),
        ):
            with self.subTest(key=key, bad=bad), patch.dict(os.environ, {**RESOURCES, key: bad}):
                with self.assertRaises(ValueError):
                    hooks.deployment_resource_paths()


class JobTests(QuietTest):
    def setUp(self):
        super().setUp()
        self.now = 0
        self.enterContext(patch.object(hooks.time, "monotonic", side_effect=lambda: self.now))
        self.sleep = self.enterContext(patch.object(hooks.time, "sleep", side_effect=self.advance))
        self.client = Mock()

    def advance(self, seconds):
        self.now += seconds

    def test_only_the_newly_started_execution_is_polled_until_success(self):
        self.client.request.side_effect = [
            response(EXECUTION), response(execution("Processing")),
            response(execution("Running")), response(execution()),
        ]
        hooks.run_private_seed_job(self.client, JOB)
        self.assertEqual(
            [(c.args[0], c.args[1]) for c in self.client.request.call_args_list],
            [("POST", api(JOB + "/start"))] + [
                ("GET", api(JOB + "/executions/" + NAME)),
            ] * 3,
        )
        self.assertTrue(all(c.args[2] == 1800 for c in self.client.request.call_args_list))
        self.assertEqual(self.sleep.call_args_list, [call(10), call(10)])

    def test_failed_and_stopped_executions_are_fatal(self):
        for state in ("Failed", "Stopped"):
            with self.subTest(state=state):
                self.client.request.side_effect = [response(EXECUTION), response(execution(state))]
                with self.assertRaisesRegex(RuntimeError, state):
                    hooks.run_private_seed_job(self.client, JOB)
        self.sleep.assert_not_called()

    def test_pending_execution_has_a_bounded_timeout(self):
        for state in ("Running", "Processing", "Degraded", "Unknown"):
            with self.subTest(state=state):
                self.now = 0
                self.client.request.side_effect = lambda method, *_: response(
                    EXECUTION if method == "POST" else execution(state)
                )
                with self.assertRaisesRegex(TimeoutError, "timed out"):
                    hooks.run_private_seed_job(self.client, JOB, timeout=3, interval=2)
                self.assertEqual(self.now, 3)

    def test_invalid_timeout_cannot_remove_the_bound(self):
        for values in ({"timeout": 0}, {"interval": 0}, {"timeout": -1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                hooks.run_private_seed_job(self.client, JOB, **values)
        self.client.request.assert_not_called()

    def test_start_requires_a_safe_execution_name_and_matching_resource_id(self):
        for body in (
            None, {}, [], {"name": NAME + "/../../other"}, {"name": "../other"},
            {"name": NAME + "?api-version=bad"}, {"name": NAME + "%2fother"},
            {"name": ["nested"]}, {"name": "another-job-old"}, {"name": ""},
            {**EXECUTION, "id": EXECUTION["id"] + "/other"},
            {**EXECUTION, "id": None},
        ):
            with self.subTest(body_type=type(body).__name__):
                self.client.request.reset_mock()
                self.client.request.side_effect = None
                self.client.request.return_value = response(body)
                with self.assertRaises((RuntimeError, ValueError)):
                    hooks.run_private_seed_job(self.client, JOB)
                self.client.request.assert_called_once()

    def test_a_different_successful_execution_cannot_satisfy_the_gate(self):
        for body in (
            execution(name="gsdr-app-seed-old"),
            execution(name="gsdr-app-seed-old", id=JOB + "/executions/gsdr-app-seed-old"),
            execution(id=EXECUTION["id"].replace("rg-test", "rg-other")),
        ):
            with self.subTest(body=body):
                self.client.request.side_effect = [response(EXECUTION), response(body)]
                with self.assertRaises(RuntimeError):
                    hooks.run_private_seed_job(self.client, JOB)
        self.sleep.assert_not_called()

    def test_missing_unknown_or_nested_execution_status_fails(self):
        for properties in (None, [], {}, {"status": None}, {"status": ["Succeeded"]},
                           {"status": "Completed"}, {"status": 1}):
            with self.subTest(properties=properties):
                self.client.request.side_effect = [
                    response(EXECUTION), response(execution(properties=properties)),
                ]
                with self.assertRaisesRegex(RuntimeError, "malformed"):
                    hooks.run_private_seed_job(self.client, JOB)

    def test_async_start_polls_its_location_then_only_its_execution(self):
        self.client.request.side_effect = [
            response(status=202, location=LOCATION),
            response(status=202),
            response(EXECUTION),
            response(execution()),
        ]
        hooks.run_private_seed_job(self.client, JOB)
        paths = [c.args[1] for c in self.client.request.call_args_list]
        self.assertEqual(paths, [
            api(JOB + "/start"), LOCATION.removeprefix(hooks.ARM_ENDPOINT),
            LOCATION.removeprefix(hooks.ARM_ENDPOINT), api(EXECUTION["id"]),
        ])

    def test_async_start_with_execution_body_does_not_need_a_location(self):
        self.client.request.side_effect = [
            response(EXECUTION, status=202), response(execution()),
        ]
        hooks.run_private_seed_job(self.client, JOB)
        self.assertEqual(self.client.request.call_count, 2)

    def test_async_start_locations_cannot_redirect_tokens_or_change_resource_scope(self):
        for location in (
            None, "https://attacker.example/", LOCATION.replace("https:", "http:"),
            LOCATION.replace("management.azure.com", "management.azure.com.attacker.example"),
            LOCATION.replace("management.azure.com", "user@management.azure.com"),
            LOCATION.replace(SUBSCRIPTION, CLIENT_ID),
            LOCATION.replace("operationResults/1234", "operationResults/../1234"),
            LOCATION.replace("operationResults/1234", "operationResults/%2e%2e/1234"),
            LOCATION.replace("2024-03-01", "2025-01-01"),
            LOCATION + "#fragment", LOCATION + "&redirect=https://attacker.example",
        ):
            with self.subTest(location=location):
                self.client.request.reset_mock()
                self.client.request.side_effect = None
                self.client.request.return_value = response(status=202, location=location)
                with self.assertRaisesRegex(RuntimeError, "Location"):
                    hooks.run_private_seed_job(self.client, JOB)
                self.client.request.assert_called_once()

    def test_async_start_times_out_without_starting_another_job(self):
        self.client.request.return_value = response(status=202, location=LOCATION)
        with self.assertRaises(TimeoutError):
            hooks.run_private_seed_job(self.client, JOB, timeout=2, interval=1)
        self.assertEqual(
            sum(c.args[0] == "POST" for c in self.client.request.call_args_list), 1,
        )

    def test_api_errors_are_not_silently_retried_or_replaced_with_history(self):
        for replies in (
            [RuntimeError("ARM failed")],
            [response(EXECUTION), RuntimeError("ARM failed")],
        ):
            self.client.request.side_effect = replies
            with self.assertRaisesRegex(RuntimeError, "ARM failed"):
                hooks.run_private_seed_job(self.client, JOB)
        self.sleep.assert_not_called()


class ArmTransportTests(QuietTest):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(hooks.time, "monotonic", return_value=0))
        self.credential = Mock()
        self.credential.get_token.return_value = SimpleNamespace(token=FAKE_TOKEN)
        self.opener = Mock()
        self.enterContext(patch.object(hooks, "build_opener", return_value=self.opener))
        self.client = hooks.ArmClient(self.credential)

    def reply(self, body, status=200, headers=None):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = status
        response.headers = headers or {}
        response.read.return_value = body
        self.opener.open.return_value = response
        return response

    def test_arm_scope_and_bearer_auth_are_used_without_token_output(self):
        self.reply(json.dumps(EXECUTION).encode())
        self.assertEqual(
            self.client.request("POST", api(JOB + "/start"), 1800),
            response(EXECUTION),
        )
        self.credential.get_token.assert_called_once_with("https://management.azure.com/.default")
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, hooks.ARM_ENDPOINT + api(JOB + "/start"))
        self.assertEqual(request.get_method(), "POST")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("Authorization"), "Bearer " + FAKE_TOKEN)
        self.assertEqual(self.opener.open.call_args.kwargs["timeout"], 30)
        self.assertNotIn(FAKE_TOKEN, sys.stdout.getvalue() + sys.stderr.getvalue())

    def test_api_and_auth_errors_are_sanitized(self):
        for error in (
            HTTPError("https://management.azure.com", 403, FAKE_TOKEN, {}, None),
            URLError(FAKE_TOKEN), OSError(FAKE_TOKEN),
        ):
            self.opener.open.side_effect = error
            with self.assertRaises(RuntimeError) as caught:
                self.client.request("GET", api(APP), 100)
            self.assertNotIn(FAKE_TOKEN, str(caught.exception))
        self.credential.get_token.side_effect = RuntimeError(FAKE_TOKEN)
        with self.assertRaisesRegex(RuntimeError, "Azure Developer CLI") as caught:
            self.client.request("GET", api(APP), 100)
        self.assertNotIn(FAKE_TOKEN, str(caught.exception))

    def test_malformed_oversized_error_and_wrong_status_responses_fail(self):
        for body, status in (
            (b"not-json", 200), (b"null", 200), (b"[]", 200), (b'"value"', 200),
            (b'"Restart succeeded"', 200),
            (b"\xff", 200), (b"x" * 2_000_001, 200),
            (json.dumps({"error": {"message": FAKE_TOKEN}}).encode(), 200),
            (b"{}", 204), (b"{}", 301), (b"{}", 500),
        ):
            with self.subTest(status=status, body_length=len(body)):
                self.reply(body, status)
                with self.assertRaises(RuntimeError) as caught:
                    self.client.request("GET", api(APP), 100)
                self.assertNotIn(FAKE_TOKEN, str(caught.exception))

    def test_empty_restart_and_async_start_responses_are_supported(self):
        for body in (b"", b"null", b'"Restart succeeded"'):
            with self.subTest(body=body):
                self.reply(body)
                self.assertEqual(
                    self.client.request("POST", api(APP + "/revisions/rev/restart"), 100),
                    response(),
                )
        self.reply(b"", 202, {"Location": LOCATION})
        self.assertEqual(self.client.request("POST", api(JOB + "/start"), 100),
                         response(status=202, location=LOCATION))

    def test_restart_ack_is_not_accepted_for_job_start_or_unsuccessful_messages(self):
        for path, body in (
            (JOB + "/start", b'"Restart succeeded"'),
            (APP + "/revisions/rev/restart", b'"Restart failed"'),
        ):
            with self.subTest(path=path, body=body):
                self.reply(body)
                with self.assertRaisesRegex(RuntimeError, "JSON object"):
                    self.client.request("POST", api(path), 100)

    def test_deadline_limits_http_waits_and_prevents_late_requests(self):
        self.reply(b"{}")
        self.client.request("GET", api(APP), 2)
        self.assertEqual(self.opener.open.call_args.kwargs["timeout"], 2)
        self.opener.open.reset_mock()
        with self.assertRaises(TimeoutError):
            self.client.request("GET", api(APP), 0)
        self.opener.open.assert_not_called()

    def test_redirect_handler_never_forwards_bearer_tokens(self):
        self.assertIsNone(hooks._NoArmRedirects().redirect_request(
            Mock(), Mock(), 302, "redirect", {}, "https://attacker.example",
        ))


class RestartTests(QuietTest):
    def setUp(self):
        super().setUp()
        self.client = Mock()
        self.ready = {"properties": {"latestReadyRevisionName": "gsdr-app--new123"}}

    def test_restart_targets_the_returned_ready_revision(self):
        self.client.request.side_effect = [response(self.ready), response()]
        hooks.restart_application(self.client, APP)
        self.assertEqual(
            [(c.args[0], c.args[1]) for c in self.client.request.call_args_list],
            [("GET", api(APP)), ("POST", api(APP + "/revisions/gsdr-app--new123/restart"))],
        )

    def test_missing_malformed_or_other_application_revision_is_rejected(self):
        for ready in (
            None, {}, {"properties": []}, {"properties": {}},
            {"properties": {"latestReadyRevisionName": None}},
            {"properties": {"latestReadyRevisionName": ["gsdr-app--new123"]}},
            {"properties": {"latestReadyRevisionName": "other-app--new123"}},
            {"properties": {"latestReadyRevisionName": "gsdr-app--new123/../../other"}},
            {"properties": {"latestReadyRevisionName": "gsdr-app--new123?query=bad"}},
        ):
            with self.subTest(ready=ready):
                self.client.request.reset_mock()
                self.client.request.return_value = response(ready)
                with self.assertRaises((RuntimeError, ValueError)):
                    hooks.restart_application(self.client, APP)
                self.client.request.assert_called_once()

    def test_restart_api_failures_and_unconfirmed_restart_are_fatal(self):
        for result in (RuntimeError("restart failed"), response(status=202)):
            self.client.request.side_effect = [response(self.ready), result]
            with self.assertRaises(RuntimeError):
                hooks.restart_application(self.client, APP)


class PostdeployTests(QuietTest):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.dict(os.environ, {
            **RESOURCES, "APP_URL": "https://app.example", "AZURE_TENANT_ID": TENANT_ID,
            "AZURE_TOKEN_CREDENTIALS": "AzureCliCredential",
        }))
        self.credential = MagicMock()
        self.credential.__enter__.return_value = self.credential
        identity = ModuleType("azure.identity")
        identity.AzureDeveloperCliCredential = Mock(return_value=self.credential)
        self.identity = identity
        self.enterContext(patch.dict(sys.modules, {"azure.identity": identity}))
        self.client = self.enterContext(patch.object(hooks, "ArmClient"))
        self.seed = self.enterContext(patch.object(hooks, "run_private_seed_job"))
        self.restart = self.enterContext(patch.object(hooks, "restart_application"))
        self.verify = self.enterContext(patch.object(hooks, "verify_application"))

    def test_azd_identity_is_pinned_then_seed_restart_and_strict_verification_are_ordered(self):
        calls = Mock()
        calls.attach_mock(self.seed, "seed")
        calls.attach_mock(self.restart, "restart")
        calls.attach_mock(self.verify, "verify")
        hooks.postdeploy()
        self.identity.AzureDeveloperCliCredential.assert_called_once_with(
            tenant_id=TENANT_ID, process_timeout=30,
        )
        self.client.assert_called_once_with(self.credential)
        self.assertEqual(calls.mock_calls, [
            call.seed(self.client.return_value, JOB),
            call.restart(self.client.return_value, APP),
            call.verify("https://app.example"),
        ])
        self.credential.__exit__.assert_called_once()

    def test_seed_failure_stops_restart_and_verification(self):
        self.seed.side_effect = RuntimeError("seed failed")
        self.assertEqual(hooks.main(["--phase", "postdeploy"]), 1)
        self.restart.assert_not_called()
        self.verify.assert_not_called()
        self.credential.__exit__.assert_called_once()

    def test_restart_failure_stops_verification(self):
        self.restart.side_effect = RuntimeError("restart failed")
        self.assertEqual(hooks.main(["--phase", "postdeploy"]), 1)
        self.verify.assert_not_called()

    def test_strict_application_failure_remains_fatal(self):
        self.verify.side_effect = hooks.VerificationError("knowledgeSource is local")
        self.assertEqual(hooks.main(["--phase", "postdeploy"]), 1)
        self.restart.assert_called_once()

    def test_application_url_precedence_and_missing_url(self):
        with patch.dict(os.environ, {"SERVICE_APP_ENDPOINT_URL": "https://fallback.example"}):
            hooks.postdeploy()
            self.verify.assert_called_with("https://app.example")
            with patch.dict(os.environ, {"APP_URL": ""}):
                hooks.postdeploy()
                self.verify.assert_called_with("https://fallback.example")
        with patch.dict(os.environ, {"APP_URL": ""}):
            self.seed.reset_mock()
            with self.assertRaisesRegex(RuntimeError, "Missing azd output"):
                hooks.postdeploy()
            self.seed.assert_not_called()


class RunnerTests(QuietTest):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.dict(os.environ, {
            **{key: "configured" for key in hooks.REQUIRED_OUTPUTS},
            "AZURE_CLIENT_ID": CLIENT_ID, "AZURE_TOKEN_CREDENTIALS": "ManagedIdentityCredential",
            "GSDR_AZD_HOOK": "0", "PYTHON_DOTENV_DISABLED": "0",
        }))
        self.native = self.enterContext(patch.object(runner, "run_native"))

    def test_seed_then_agents_use_python_modules_and_only_runtime_managed_identity(self):
        self.assertEqual(runner.main(), 0)
        self.assertEqual([c.args[0] for c in self.native.call_args_list], [
            [sys.executable, "-m", "scripts.seed"],
            [sys.executable, "-m", "scripts.provision_agents"],
        ])
        for command in self.native.call_args_list:
            env = command.kwargs["env"]
            self.assertEqual(env["AZURE_TOKEN_CREDENTIALS"], "ManagedIdentityCredential")
            self.assertEqual(env["AZURE_CLIENT_ID"], CLIENT_ID)
            self.assertEqual(env["GSDR_AZD_HOOK"], "1")
            self.assertEqual(env["PYTHON_DOTENV_DISABLED"], "1")
        self.assertEqual(os.environ["GSDR_AZD_HOOK"], "0")
        self.assertEqual(os.environ["PYTHON_DOTENV_DISABLED"], "0")

    def test_unpinned_credential_or_missing_client_id_cannot_fall_back(self):
        for key, value in (
            ("AZURE_TOKEN_CREDENTIALS", ""), ("AZURE_TOKEN_CREDENTIALS", "AzureDeveloperCliCredential"),
            ("AZURE_TOKEN_CREDENTIALS", "prod"), ("AZURE_CLIENT_ID", ""),
            ("AZURE_CLIENT_ID", "not-a-guid"),
            ("AZURE_CLIENT_ID", "00000000-0000-0000-0000-000000000000"),
        ):
            with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}):
                self.assertEqual(runner.main(), 1)
        self.native.assert_not_called()

    def test_missing_outputs_prevent_native_execution(self):
        with patch.dict(os.environ, {"COSMOS_ENDPOINT": ""}):
            self.assertEqual(runner.main(), 1)
        self.native.assert_not_called()

    def test_stage_failures_are_fatal_and_never_run_later_stages(self):
        for expected_calls in (1, 2):
            self.native.reset_mock()
            self.native.side_effect = (
                [None] * (expected_calls - 1)
                + [subprocess.CalledProcessError(8, ["python"])]
            )
            self.assertEqual(runner.main(), 1)
            self.assertEqual(self.native.call_count, expected_calls)
            self.assertIn("failed (exit 8)", sys.stderr.getvalue())

    def test_modules_run_from_repository_or_image_root_without_installs(self):
        with patch.object(hooks.subprocess, "run") as native:
            hooks.run_native([sys.executable, "-m", "scripts.seed"], env={})
        native.assert_called_once_with(
            [sys.executable, "-m", "scripts.seed"],
            cwd=ROOT, env={}, check=True, text=True, capture_output=False,
        )
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("WORKDIR /app", dockerfile)
        self.assertIn("COPY scripts ./scripts", dockerfile)
        self.assertIn("COPY src/backend/app ./app", dockerfile)
        self.assertIn("COPY data ./data", dockerfile)
        self.assertIn(
            "azure-identity>=1.24.0",
            (ROOT / "src" / "backend" / "requirements.txt").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
