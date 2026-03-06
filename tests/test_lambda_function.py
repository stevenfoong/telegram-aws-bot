"""
Unit tests for src/lambda_function.py.

All AWS calls (SSM, Step Functions) and the Telegram sendMessage HTTP request
are mocked so that no real network or AWS access is needed.
"""

import importlib
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(body: dict, secret_token: str = "test-secret") -> dict:
    """Build a minimal API-Gateway-style event."""
    return {
        "headers": {"X-Telegram-Bot-Api-Secret-Token": secret_token},
        "body": json.dumps(body),
    }


def _private_message(user_id: int, text: str) -> dict:
    """Return a Telegram update with a private message."""
    return {
        "message": {
            "from": {"id": user_id, "first_name": "Alice"},
            "chat": {"id": user_id, "type": "private"},
            "text": text,
        }
    }


def _group_message(user_id: int, group_id: int, text: str) -> dict:
    """Return a Telegram update with a group message."""
    return {
        "message": {
            "from": {"id": user_id, "first_name": "Alice"},
            "chat": {"id": group_id, "type": "group"},
            "text": text,
        }
    }


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestLambdaFunction(unittest.TestCase):

    # ------------------------------------------------------------------
    # Module-level setup: patch boto3 before importing the module so that
    # no real boto3 client is ever created.
    # ------------------------------------------------------------------

    def setUp(self):
        # Environment variables expected by the Lambda
        self.env_vars = {
            "SSM_BOT_TOKEN_PARAM": "/bot/token",
            "SSM_SECRET_TOKEN_PARAM": "/bot/secret",
            "SSM_WHITELIST_PARAM": "/bot/whitelist",
            "STEP_FUNCTION_ARN_DIAGNOSTIC": "arn:aws:states:us-east-1:123456789012:stateMachine:Diagnostic",
            "STEP_FUNCTION_ARN_REBOOT": "arn:aws:states:us-east-1:123456789012:stateMachine:Reboot",
        }

        # Mock SSM responses
        self.mock_ssm = MagicMock()
        self.mock_ssm.get_parameter.side_effect = self._ssm_get_parameter

        # Mock Step Functions responses
        self.mock_sfn = MagicMock()
        self.mock_sfn.start_execution.return_value = {
            "executionArn": "arn:aws:states:us-east-1:123456789012:execution:Diagnostic:exec-id-1234"
        }

        # Patch boto3.client to return the appropriate mock
        def fake_boto3_client(service, **kwargs):
            if service == "ssm":
                return self.mock_ssm
            if service == "stepfunctions":
                return self.mock_sfn
            raise ValueError(f"Unexpected service: {service}")

        # We need to reload the module for each test so that the cached SSM
        # values and module-level boto3 clients are replaced by our mocks.
        patcher_boto3 = patch("boto3.client", side_effect=fake_boto3_client)
        patcher_boto3.start()
        self.addCleanup(patcher_boto3.stop)

        patcher_env = patch.dict("os.environ", self.env_vars)
        patcher_env.start()
        self.addCleanup(patcher_env.stop)

        # Remove cached module so it re-imports with our patches applied.
        sys.modules.pop("lambda_function", None)

        # Insert src/ onto the path so we can import the module directly.
        # Use a path relative to this test file so tests are portable.
        src_dir = os.path.join(os.path.dirname(__file__), "..", "src")
        src_dir = os.path.abspath(src_dir)
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)

        self.module = importlib.import_module("lambda_function")
        # Reset the SSM in-memory cache between tests.
        self.module._ssm_cache.clear()

    # ------------------------------------------------------------------
    # SSM stub
    # ------------------------------------------------------------------

    SSM_DATA = {
        "/bot/token": "123456:ABC-bot-token",
        "/bot/secret": "test-secret",
        "/bot/whitelist": "111,222,333",
    }

    def _ssm_get_parameter(self, Name, WithDecryption=True):
        if Name in self.SSM_DATA:
            return {"Parameter": {"Value": self.SSM_DATA[Name]}}
        raise KeyError(f"Unknown SSM parameter: {Name}")

    # ------------------------------------------------------------------
    # Helper: call lambda_handler with mocked send_telegram_message
    # ------------------------------------------------------------------

    def _call(self, event):
        with patch.object(self.module, "send_telegram_message", return_value={}) as mock_send:
            result = self.module.lambda_handler(event, None)
        return result, mock_send

    # ------------------------------------------------------------------
    # Authentication tests
    # ------------------------------------------------------------------

    def test_invalid_secret_token_returns_403(self):
        event = _make_event(_private_message(111, "/whoami"), secret_token="wrong-token")
        result, _ = self._call(event)
        self.assertEqual(result["statusCode"], 403)

    def test_missing_secret_token_returns_403(self):
        event = {"headers": {}, "body": json.dumps(_private_message(111, "/whoami"))}
        result, _ = self._call(event)
        self.assertEqual(result["statusCode"], 403)

    def test_lowercase_header_name_accepted(self):
        """API Gateway may lowercase header names."""
        event = {
            "headers": {"x-telegram-bot-api-secret-token": "test-secret"},
            "body": json.dumps(_private_message(111, "/whoami")),
        }
        result, mock_send = self._call(event)
        self.assertEqual(result["statusCode"], 200)
        mock_send.assert_called_once()

    def test_unauthorised_user_ignored(self):
        """User IDs not in the whitelist must be silently ignored."""
        event = _make_event(_private_message(999, "/whoami"))
        result, mock_send = self._call(event)
        self.assertEqual(result["statusCode"], 200)
        mock_send.assert_not_called()

    # ------------------------------------------------------------------
    # /whoami tests
    # ------------------------------------------------------------------

    def test_whoami_private_chat(self):
        event = _make_event(_private_message(111, "/whoami"))
        result, mock_send = self._call(event)
        self.assertEqual(result["statusCode"], 200)
        args = mock_send.call_args[0]
        self.assertIn("111", args[1])
        # Group ID should NOT appear for a private chat
        self.assertNotIn("Group ID", args[1])

    def test_whoami_group_chat(self):
        event = _make_event(_group_message(111, -100987654321, "/whoami"))
        result, mock_send = self._call(event)
        self.assertEqual(result["statusCode"], 200)
        args = mock_send.call_args[0]
        self.assertIn("111", args[1])
        self.assertIn("Group ID", args[1])
        self.assertIn("-100987654321", args[1])

    def test_whoami_with_bot_suffix(self):
        """Commands like /whoami@MyBot should be handled correctly."""
        event = _make_event(_private_message(111, "/whoami@MyAwesomeBot"))
        result, mock_send = self._call(event)
        self.assertEqual(result["statusCode"], 200)
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        self.assertIn("111", args[1])

    # ------------------------------------------------------------------
    # /diagnostic tests
    # ------------------------------------------------------------------

    def test_diagnostic_triggers_step_function(self):
        event = _make_event(_private_message(111, "/diagnostic"))
        result, mock_send = self._call(event)
        self.assertEqual(result["statusCode"], 200)
        self.mock_sfn.start_execution.assert_called_once()
        call_kwargs = self.mock_sfn.start_execution.call_args[1]
        self.assertEqual(
            call_kwargs["stateMachineArn"],
            self.env_vars["STEP_FUNCTION_ARN_DIAGNOSTIC"],
        )
        mock_send.assert_called_once()
        reply = mock_send.call_args[0][1]
        self.assertIn("Diagnostic", reply)

    def test_diagnostic_missing_arn(self):
        del self.env_vars["STEP_FUNCTION_ARN_DIAGNOSTIC"]
        with patch.dict("os.environ", self.env_vars, clear=False):
            # Clear the specific key
            import os as _os
            _os.environ.pop("STEP_FUNCTION_ARN_DIAGNOSTIC", None)
            event = _make_event(_private_message(111, "/diagnostic"))
            result, mock_send = self._call(event)
        self.assertEqual(result["statusCode"], 200)
        self.mock_sfn.start_execution.assert_not_called()
        reply = mock_send.call_args[0][1]
        self.assertIn("not configured", reply)

    # ------------------------------------------------------------------
    # /reboot tests
    # ------------------------------------------------------------------

    def test_reboot_triggers_step_function(self):
        event = _make_event(_private_message(222, "/reboot"))
        result, mock_send = self._call(event)
        self.assertEqual(result["statusCode"], 200)
        self.mock_sfn.start_execution.assert_called_once()
        call_kwargs = self.mock_sfn.start_execution.call_args[1]
        self.assertEqual(
            call_kwargs["stateMachineArn"],
            self.env_vars["STEP_FUNCTION_ARN_REBOOT"],
        )
        mock_send.assert_called_once()
        reply = mock_send.call_args[0][1]
        self.assertIn("Reboot", reply)

    def test_reboot_missing_arn(self):
        import os as _os
        _os.environ.pop("STEP_FUNCTION_ARN_REBOOT", None)
        event = _make_event(_private_message(222, "/reboot"))
        result, mock_send = self._call(event)
        self.assertEqual(result["statusCode"], 200)
        self.mock_sfn.start_execution.assert_not_called()
        reply = mock_send.call_args[0][1]
        self.assertIn("not configured", reply)

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_unknown_command_returns_help(self):
        event = _make_event(_private_message(111, "/foobar"))
        result, mock_send = self._call(event)
        self.assertEqual(result["statusCode"], 200)
        reply = mock_send.call_args[0][1]
        self.assertIn("Unknown command", reply)
        self.assertIn("/whoami", reply)

    def test_plain_text_message_ignored(self):
        event = _make_event(_private_message(111, "hello world"))
        result, mock_send = self._call(event)
        self.assertEqual(result["statusCode"], 200)
        mock_send.assert_not_called()

    def test_update_without_message_ignored(self):
        body = {"edited_message": {"text": "edited"}}
        event = _make_event(body)
        result, mock_send = self._call(event)
        self.assertEqual(result["statusCode"], 200)
        mock_send.assert_not_called()

    def test_invalid_json_body_returns_400(self):
        event = {
            "headers": {"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            "body": "not-valid-json",
        }
        result, _ = self._call(event)
        self.assertEqual(result["statusCode"], 400)

    def test_ssm_cache_is_used(self):
        """SSM should be queried only once per parameter per container lifecycle."""
        event = _make_event(_private_message(111, "/whoami"))
        self._call(event)
        self._call(event)
        # The whitelist param is fetched once (cached) across both invocations.
        param_names = [
            call[1]["Name"]
            for call in self.mock_ssm.get_parameter.call_args_list
        ]
        self.assertEqual(param_names.count("/bot/whitelist"), 1)

    # ------------------------------------------------------------------
    # parse_command unit tests
    # ------------------------------------------------------------------

    def test_parse_command_basic(self):
        self.assertEqual(self.module.parse_command("/whoami"), "/whoami")

    def test_parse_command_with_bot_suffix(self):
        self.assertEqual(self.module.parse_command("/whoami@TestBot"), "/whoami")

    def test_parse_command_uppercase(self):
        self.assertEqual(self.module.parse_command("/WHOAMI"), "/whoami")

    def test_parse_command_empty(self):
        self.assertEqual(self.module.parse_command(""), "")

    def test_parse_command_with_args(self):
        self.assertEqual(self.module.parse_command("/reboot now"), "/reboot")


if __name__ == "__main__":
    unittest.main()
