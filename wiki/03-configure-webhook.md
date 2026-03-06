# How to Configure the Telegram Webhook

After deploying the Lambda and API Gateway, you must tell Telegram where to send updates. Telegram uses a webhook — it POSTs a JSON payload to your URL every time a user sends a message to your bot.

---

## Prerequisites

- The **Webhook URL** from the API Gateway step (e.g. `https://abc123.execute-api.us-east-1.amazonaws.com/prod/webhook`).
- The **Bot Token** from BotFather (e.g. `123456789:ABCDefGHIjklMNOpqrsTUVwxyz`).
- The **Webhook Secret Token** you stored in SSM (the random hex string you generated).

---

## Step 1 — Register the webhook

Run the following command, replacing the placeholders with your real values:

```bash
BOT_TOKEN="123456789:ABCDefGHIjklMNOpqrsTUVwxyz"
WEBHOOK_URL="https://abc123.execute-api.us-east-1.amazonaws.com/prod/webhook"
SECRET_TOKEN="<your-random-secret-hex>"

curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{
    \"url\": \"${WEBHOOK_URL}\",
    \"secret_token\": \"${SECRET_TOKEN}\",
    \"allowed_updates\": [\"message\"]
  }"
```

A successful response looks like:

```json
{
  "ok": true,
  "result": true,
  "description": "Webhook was set"
}
```

---

## Step 2 — Verify the webhook is registered

```bash
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo" | python3 -m json.tool
```

Look for:

| Field | Expected value |
|-------|----------------|
| `url` | Your API Gateway URL |
| `has_custom_certificate` | `false` (API Gateway uses AWS certificates) |
| `pending_update_count` | `0` |
| `last_error_message` | Not present (or empty) |

---

## Step 3 — Test the bot

1. Open Telegram and find your bot by its username.
2. Send:

   ```
   /whoami
   ```

   You should receive a reply containing your numeric Telegram user ID.

3. Try from a group chat:
   - Add the bot to a group.
   - Send `/whoami` — the reply should include both your user ID and the group ID.

---

## Troubleshooting

### Telegram replies "Forbidden"

Your `X-Telegram-Bot-Api-Secret-Token` does not match what is stored in SSM.
Double-check that the value you passed to `setWebhook` as `secret_token` exactly matches the value stored at `/telegram-bot/webhook-secret-token` in SSM.

### Bot doesn't reply — Lambda logs show "Unauthorised user"

Your Telegram user ID is not in the whitelist stored at `/telegram-bot/allowed-user-ids` in SSM.

Fetch your user ID by sending `/whoami` via a quick no-auth local test, or message `@userinfobot` on Telegram, then add the ID to the SSM parameter:

```bash
aws ssm put-parameter \
  --name "/telegram-bot/allowed-user-ids" \
  --value "111111111,222222222,333333333" \
  --type StringList \
  --overwrite
```

### Bot doesn't reply — Lambda logs show an exception

Check the Lambda function logs in **CloudWatch Logs** under the log group `/aws/lambda/telegram-bot-webhook`.

---

## Removing the webhook

If you need to remove the webhook (e.g. to use long-polling during local development):

```bash
curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/deleteWebhook"
```

---

## Architecture overview

```
User (Telegram)
      │  POST update (JSON)
      ▼
API Gateway  ──►  Lambda (telegram-bot-webhook)
                       │
                       ├─ SSM: verify secret token, load whitelist, get bot token
                       │
                       ├─ /whoami    ──► sendMessage (Telegram API)
                       ├─ /diagnostic ──► Step Functions (TelegramDiagnostic)
                       └─ /reboot    ──► Step Functions (TelegramReboot)
```

---

## Back to start

👉 [01 — Create a Telegram Bot](01-create-telegram-bot.md)
👉 [02 — AWS Setup](02-aws-setup.md)
