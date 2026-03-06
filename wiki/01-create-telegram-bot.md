# How to Create a Telegram Bot

This guide walks you through creating a Telegram bot using **BotFather** — the official Telegram tool for managing bots.

---

## Prerequisites

- A Telegram account (mobile app or desktop).

---

## Step 1 — Open BotFather

1. Open Telegram and search for **@BotFather** (the verified blue-tick account).
2. Start a conversation by clicking **Start** or sending `/start`.

---

## Step 2 — Create a new bot

1. Send the command:

   ```
   /newbot
   ```

2. BotFather will ask for a **display name** for your bot.
   Enter a friendly name, for example:

   ```
   My AWS Admin Bot
   ```

3. BotFather will then ask for a **username** — this must end with `bot` and be globally unique.
   Enter something like:

   ```
   my_aws_admin_bot
   ```

4. BotFather will reply with your **Bot Token**. It looks like:

   ```
   123456789:ABCDefGHIjklMNOpqrsTUVwxyz
   ```

   > ⚠️ **Keep this token secret.** Anyone who has it can control your bot.

---

## Step 3 — (Optional) Add commands to BotFather

Setting command hints makes the bot easier to use. Send the following to BotFather:

```
/setcommands
```

Select your bot, then paste:

```
whoami - Show your user ID (and group ID if in a group)
diagnostic - Run a diagnostic check on the servers
reboot - Reboot the server
```

---

## Step 4 — Store the Bot Token in AWS SSM

The Lambda function retrieves the token from **AWS Systems Manager Parameter Store** rather than hard-coding it.

```bash
aws ssm put-parameter \
  --name "/telegram-bot/bot-token" \
  --value "123456789:ABCDefGHIjklMNOpqrsTUVwxyz" \
  --type SecureString \
  --description "Telegram Bot Token"
```

---

## Next step

👉 [02 — AWS Setup](02-aws-setup.md)
