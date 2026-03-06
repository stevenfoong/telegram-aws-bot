# AWS Setup Guide

This guide creates all the AWS resources needed to run the Telegram bot Lambda.

---

## Prerequisites

- AWS CLI installed and configured (`aws configure`).
- Sufficient IAM permissions to create Lambda functions, API Gateway, SSM parameters, Step Functions, and IAM roles.

---

## 1 — Store secrets in SSM Parameter Store

### 1a — Bot Token (already done in step 01)

```bash
aws ssm put-parameter \
  --name "/telegram-bot/bot-token" \
  --value "<YOUR_BOT_TOKEN>" \
  --type SecureString \
  --description "Telegram Bot Token"
```

### 1b — Webhook secret token

This is a random string **you choose**. Telegram will include it in every webhook request so your Lambda can verify the request is genuine.

Generate a secure random value:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Store it in SSM:

```bash
aws ssm put-parameter \
  --name "/telegram-bot/webhook-secret-token" \
  --value "<YOUR_RANDOM_SECRET>" \
  --type SecureString \
  --description "Telegram Webhook Secret Token"
```

### 1c — Allowed user ID whitelist

The Lambda only processes messages from Telegram user IDs in this list.

**How to find your Telegram user ID**: message `@userinfobot` on Telegram — it will reply with your numeric user ID.

```bash
aws ssm put-parameter \
  --name "/telegram-bot/allowed-user-ids" \
  --value "111111111,222222222" \
  --type StringList \
  --description "Comma-separated list of authorised Telegram user IDs"
```

---

## 2 — Create an IAM role for the Lambda

```bash
# Create the trust policy document
cat > /tmp/lambda-trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create the role
aws iam create-role \
  --role-name telegram-bot-lambda-role \
  --assume-role-policy-document file:///tmp/lambda-trust-policy.json

# Attach the basic Lambda execution policy (CloudWatch Logs)
aws iam attach-role-policy \
  --role-name telegram-bot-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

### 2a — Add permissions for SSM and Step Functions

```bash
cat > /tmp/telegram-bot-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SSMRead",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter"
      ],
      "Resource": [
        "arn:aws:ssm:*:*:parameter/telegram-bot/*"
      ]
    },
    {
      "Sid": "KMSDecrypt",
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt"
      ],
      "Resource": [
        "arn:aws:kms:<REGION>:<ACCOUNT_ID>:alias/aws/ssm"
      ]
    },
    {
      "Sid": "StepFunctions",
      "Effect": "Allow",
      "Action": [
        "states:StartExecution"
      ],
      "Resource": [
        "arn:aws:states:<REGION>:<ACCOUNT_ID>:stateMachine:TelegramDiagnostic",
        "arn:aws:states:<REGION>:<ACCOUNT_ID>:stateMachine:TelegramReboot"
      ]
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name telegram-bot-lambda-role \
  --policy-name telegram-bot-permissions \
  --policy-document file:///tmp/telegram-bot-policy.json
```

> Replace `<REGION>` and `<ACCOUNT_ID>` with your actual AWS region and account ID before saving the policy file.
> If you are using a **customer-managed KMS key** instead of the AWS-managed `alias/aws/ssm` key, replace the KMS resource ARN with your custom key ARN.

---

## 3 — Package and deploy the Lambda function

```bash
# From the repository root
cd src/

# Create a zip package
zip ../telegram-bot-lambda.zip lambda_function.py

# Get your AWS account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region)

# Deploy the function
aws lambda create-function \
  --function-name telegram-bot-webhook \
  --runtime python3.12 \
  --role arn:aws:iam::${ACCOUNT_ID}:role/telegram-bot-lambda-role \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://../telegram-bot-lambda.zip \
  --timeout 30 \
  --environment "Variables={
    SSM_BOT_TOKEN_PARAM=/telegram-bot/bot-token,
    SSM_SECRET_TOKEN_PARAM=/telegram-bot/webhook-secret-token,
    SSM_WHITELIST_PARAM=/telegram-bot/allowed-user-ids,
    STEP_FUNCTION_ARN_DIAGNOSTIC=arn:aws:states:${REGION}:${ACCOUNT_ID}:stateMachine:TelegramDiagnostic,
    STEP_FUNCTION_ARN_REBOOT=arn:aws:states:${REGION}:${ACCOUNT_ID}:stateMachine:TelegramReboot
  }"
```

> To **update** the function code after making changes, use:
>
> ```bash
> zip ../telegram-bot-lambda.zip lambda_function.py
> aws lambda update-function-code \
>   --function-name telegram-bot-webhook \
>   --zip-file fileb://../telegram-bot-lambda.zip
> ```

---

## 4 — Create an API Gateway (HTTP API)

```bash
# Create the HTTP API
API_ID=$(aws apigatewayv2 create-api \
  --name telegram-bot-api \
  --protocol-type HTTP \
  --query ApiId \
  --output text)

echo "API ID: ${API_ID}"

# Create a Lambda integration
INTEGRATION_ID=$(aws apigatewayv2 create-integration \
  --api-id ${API_ID} \
  --integration-type AWS_PROXY \
  --integration-uri arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:telegram-bot-webhook \
  --payload-format-version 2.0 \
  --query IntegrationId \
  --output text)

# Create a POST route for the webhook
aws apigatewayv2 create-route \
  --api-id ${API_ID} \
  --route-key "POST /webhook" \
  --target integrations/${INTEGRATION_ID}

# Deploy to a stage
aws apigatewayv2 create-stage \
  --api-id ${API_ID} \
  --stage-name prod \
  --auto-deploy

# Allow API Gateway to invoke the Lambda
aws lambda add-permission \
  --function-name telegram-bot-webhook \
  --statement-id apigateway-invoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*"

# Print the webhook URL
echo "Webhook URL: https://${API_ID}.execute-api.${REGION}.amazonaws.com/prod/webhook"
```

Keep the **Webhook URL** — you'll need it in the next step.

---

## 5 — (Placeholder) Create Step Functions state machines

The Diagnostic and Reboot state machines will be developed separately. As a placeholder, create minimal pass-through state machines so the Lambda doesn't error when the ARN is set:

```bash
cat > /tmp/diagnostic-definition.json <<'EOF'
{
  "Comment": "Diagnostic state machine — to be implemented",
  "StartAt": "Placeholder",
  "States": {
    "Placeholder": {
      "Type": "Pass",
      "End": true
    }
  }
}
EOF

aws stepfunctions create-state-machine \
  --name TelegramDiagnostic \
  --role-arn arn:aws:iam::${ACCOUNT_ID}:role/telegram-bot-lambda-role \
  --definition file:///tmp/diagnostic-definition.json

aws stepfunctions create-state-machine \
  --name TelegramReboot \
  --role-arn arn:aws:iam::${ACCOUNT_ID}:role/telegram-bot-lambda-role \
  --definition file:///tmp/diagnostic-definition.json
```

---

## Next step

👉 [03 — Configure the Telegram Webhook](03-configure-webhook.md)
