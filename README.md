# telegram-aws-bot

A **beginner-friendly** Telegram bot powered by AWS Lambda that lets authorised users run infrastructure administration tasks — `/whoami`, `/diagnostic`, and `/reboot` — directly from Telegram.

## How it works

```
Telegram  ──POST──►  API Gateway  ──►  Lambda (brain)
                                           │
                                           ├── SSM Parameter Store  (secrets & user whitelist)
                                           │
                                           ├── /whoami       ──► reply with user/group ID
                                           ├── /diagnostic   ──► AWS Step Functions
                                           └── /reboot       ──► AWS Step Functions
```

## Commands

| Command | Description |
|---------|-------------|
| `/whoami` | Returns your Telegram user ID. In a group chat, also returns the group ID. |
| `/diagnostic` | Triggers the Diagnostic AWS Step Functions state machine. |
| `/reboot` | Triggers the Reboot AWS Step Functions state machine. |

## Security

- Every incoming request is verified using the `X-Telegram-Bot-Api-Secret-Token` header.
- Only Telegram user IDs stored in **AWS SSM Parameter Store** are allowed to execute commands.

## Repository structure

```
telegram-aws-bot/
├── src/
│   └── lambda_function.py   # Webhook Lambda — the "brain"
├── tests/
│   └── test_lambda_function.py
├── wiki/
│   ├── 01-create-telegram-bot.md
│   ├── 02-aws-setup.md
│   └── 03-configure-webhook.md
├── requirements-dev.txt
└── README.md
```

## Quick start

Follow the wiki guides in order:

1. [Create a Telegram Bot](wiki/01-create-telegram-bot.md)
2. [AWS Setup — Lambda, API Gateway, SSM, Step Functions](wiki/02-aws-setup.md)
3. [Configure the Telegram Webhook](wiki/03-configure-webhook.md)

## Running the tests locally

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```
