"""
Telegram Webhook Lambda — the "brain" of the telegram-aws-bot system.

Responsibilities:
  1. Verify every incoming request using the X-Telegram-Bot-Api-Secret-Token header.
  2. Authorise the caller by checking their Telegram user ID against an allow-list
     stored in AWS SSM Parameter Store.
  3. Route recognised commands to the appropriate handler:
       /whoami      — reply with the caller's user ID (and group ID when in a group).
       /diagnostic  — start the Diagnostic AWS Step Functions state machine.
       /reboot      — start the Reboot AWS Step Functions state machine.

Environment variables required
--------------------------------
SSM_BOT_TOKEN_PARAM        Path of the SSM SecureString that holds the Telegram Bot Token.
SSM_SECRET_TOKEN_PARAM     Path of the SSM SecureString that holds the webhook secret token.
SSM_WHITELIST_PARAM        Path of the SSM parameter that holds the comma-separated list of
                           allowed Telegram user IDs.
STEP_FUNCTION_ARN_DIAGNOSTIC  ARN of the Diagnostic AWS Step Functions state machine.
STEP_FUNCTION_ARN_REBOOT      ARN of the Reboot AWS Step Functions state machine.
"""

import json
import os
import urllib.request

import boto3

# ---------------------------------------------------------------------------
# AWS SDK clients — created once per Lambda container and reused.
# ---------------------------------------------------------------------------
ssm_client = boto3.client("ssm")
sfn_client = boto3.client("stepfunctions")

# In-memory cache so we don't hit SSM on every single invocation.
_ssm_cache: dict = {}


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def get_ssm_param(name: str, with_decryption: bool = True) -> str:
    """Return an SSM parameter value, using the in-memory cache where possible."""
    if name not in _ssm_cache:
        response = ssm_client.get_parameter(Name=name, WithDecryption=with_decryption)
        _ssm_cache[name] = response["Parameter"]["Value"]
    return _ssm_cache[name]


def get_bot_token() -> str:
    """Return the Telegram Bot Token from SSM."""
    return get_ssm_param(os.environ["SSM_BOT_TOKEN_PARAM"])


def get_webhook_secret_token() -> str:
    """Return the webhook secret token from SSM."""
    return get_ssm_param(os.environ["SSM_SECRET_TOKEN_PARAM"])


def get_allowed_user_ids() -> list:
    """Return the list of authorised Telegram user IDs from SSM."""
    raw = get_ssm_param(os.environ["SSM_WHITELIST_PARAM"])
    return [uid.strip() for uid in raw.split(",") if uid.strip()]


def send_telegram_message(chat_id: int, text: str) -> dict:
    """Call the Telegram sendMessage API to reply to the user."""
    bot_token = get_bot_token()
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def parse_command(text: str) -> str:
    """
    Extract the bare command from a Telegram message text.

    Telegram delivers commands as "/command" or "/command@BotName".
    This function returns the lowercase command without the "@..." suffix.
    """
    if not text:
        return ""
    token = text.split()[0].lower()
    # Strip optional @BotName suffix (e.g. "/whoami@MyBot" → "/whoami")
    return token.split("@")[0]


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def handle_whoami(update: dict) -> tuple:
    """
    Handle the /whoami command.

    Returns
    -------
    (reply_text, chat_id)
        reply_text — message to send back to the user.
        chat_id    — Telegram chat ID to send the reply to.
    """
    message = update.get("message", {})
    user = message.get("from", {})
    chat = message.get("chat", {})

    user_id = user.get("id")
    chat_id = chat.get("id")
    chat_type = chat.get("type", "private")  # 'private', 'group', 'supergroup', 'channel'

    if chat_type == "private":
        reply = f"Your User ID: {user_id}"
    else:
        reply = f"Your User ID: {user_id}\nGroup ID: {chat_id}"

    return reply, chat_id


def handle_diagnostic(update: dict) -> tuple:
    """
    Handle the /diagnostic command by starting the Diagnostic Step Functions state machine.

    Returns
    -------
    (reply_text, chat_id)
    """
    message = update.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    sfn_arn = os.environ.get("STEP_FUNCTION_ARN_DIAGNOSTIC", "")
    if not sfn_arn:
        return "Diagnostic Step Function is not configured.", chat_id

    execution_input = json.dumps({"command": "diagnostic", "chat_id": chat_id})
    response = sfn_client.start_execution(
        stateMachineArn=sfn_arn,
        input=execution_input,
    )
    execution_id = response.get("executionArn", "").split(":")[-1]
    return f"Diagnostic triggered.\nExecution ID: {execution_id}", chat_id


def handle_reboot(update: dict) -> tuple:
    """
    Handle the /reboot command by starting the Reboot Step Functions state machine.

    Returns
    -------
    (reply_text, chat_id)
    """
    message = update.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    sfn_arn = os.environ.get("STEP_FUNCTION_ARN_REBOOT", "")
    if not sfn_arn:
        return "Reboot Step Function is not configured.", chat_id

    execution_input = json.dumps({"command": "reboot", "chat_id": chat_id})
    response = sfn_client.start_execution(
        stateMachineArn=sfn_arn,
        input=execution_input,
    )
    execution_id = response.get("executionArn", "").split(":")[-1]
    return f"Reboot initiated.\nExecution ID: {execution_id}", chat_id


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context) -> dict:
    """
    AWS Lambda entry point.

    The function is invoked by API Gateway when Telegram sends a webhook update.
    It always returns HTTP 200 to Telegram (except for header/body parse errors)
    so that Telegram does not retry failed deliveries for auth/whitelist rejections.
    """
    # ------------------------------------------------------------------
    # 1. Verify X-Telegram-Bot-Api-Secret-Token header
    # ------------------------------------------------------------------
    headers = event.get("headers") or {}
    # API Gateway may normalise header names to lower-case.
    incoming_token = (
        headers.get("X-Telegram-Bot-Api-Secret-Token")
        or headers.get("x-telegram-bot-api-secret-token")
        or ""
    )
    expected_token = get_webhook_secret_token()
    if incoming_token != expected_token:
        return {"statusCode": 403, "body": "Forbidden"}

    # ------------------------------------------------------------------
    # 2. Parse the Telegram update payload
    # ------------------------------------------------------------------
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": "Bad Request"}

    message = body.get("message")
    if not message:
        # Telegram may send other update types (edited_message, etc.) — ignore them.
        return {"statusCode": 200, "body": "OK"}

    # ------------------------------------------------------------------
    # 3. Verify the caller is in the allow-list
    # ------------------------------------------------------------------
    user = message.get("from", {})
    user_id = str(user.get("id", ""))
    chat_id = message.get("chat", {}).get("id")

    if user_id not in get_allowed_user_ids():
        # Return 200 so Telegram won't retry, but don't process the request.
        print(f"Unauthorised user ID: {user_id}")
        return {"statusCode": 200, "body": "OK"}

    # ------------------------------------------------------------------
    # 4. Route the command
    # ------------------------------------------------------------------
    text = message.get("text", "")
    command = parse_command(text)

    try:
        if command == "/whoami":
            reply, send_to = handle_whoami(body)
        elif command == "/diagnostic":
            reply, send_to = handle_diagnostic(body)
        elif command == "/reboot":
            reply, send_to = handle_reboot(body)
        elif text.startswith("/"):
            # Unknown slash command — provide help text.
            reply = (
                f"Unknown command: {command}\n"
                "Available commands:\n"
                "  /whoami      — show your user ID (and group ID)\n"
                "  /diagnostic  — run a diagnostic check\n"
                "  /reboot      — reboot the server"
            )
            send_to = chat_id
        else:
            # Plain text message — ignore silently.
            return {"statusCode": 200, "body": "OK"}

        send_telegram_message(send_to, reply)

    except Exception as exc:  # pylint: disable=broad-except
        print(f"Error handling command '{command}': {exc}")
        try:
            send_telegram_message(
                chat_id,
                "An error occurred while processing your request. Please try again later.",
            )
        except Exception:  # pylint: disable=broad-except
            pass

    return {"statusCode": 200, "body": "OK"}
