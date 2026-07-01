# Backend — AWS IoT Core + Lambda + DynamoDB

Infrastructure as code (AWS CDK, TypeScript) plus the Lambda functions.

## Architecture

```
ESP32 ──MQTT/TLS──► IoT Core ──IoT Rules──► ingest Lambda ──► DynamoDB (Telemetry, Devices)
                       ▲                                         ▲
                       │ iot:Publish (commands, schedule sync)   │ read/write
App ──HTTPS+JWT──► API Gateway (HTTP API) ──► api Lambda ────────┘
                       ▲
                   Cognito (JWT authorizer)
```

- **IoT Core** is the MQTT broker; devices authenticate with per-device X.509
  certs scoped by `AcDevicePolicy`.
- **IoT Rules** route `ac/+/{telemetry,state,captured,ack}` to the **ingest**
  Lambda, which writes DynamoDB.
- **api** Lambda serves the REST API, publishes commands to `ac/{id}/command`,
  and pushes schedule lists to `ac/{id}/schedules`.
- **DynamoDB**: `Devices`, `Schedules`, `Telemetry` (TTL-expired).
- **Cognito** authenticates app users; the api Lambda enforces device ownership.

## Prerequisites

- AWS account + credentials configured (`aws configure`)
- Node.js 18+ and `npm`
- AWS CDK v2 (`npm i -g aws-cdk`) — or use the local dev dependency

## Deploy

```bash
cd backend/cdk
npm install
npx cdk bootstrap          # first time per account/region

# Recommended: turn on a billing guardrail (email alert at 80%/100% of cap).
export BUDGET_ALERT_EMAIL=you@example.com
export MONTHLY_BUDGET_USD=5

npx cdk deploy
```

Outputs printed on success:

| Output | Use |
|--------|-----|
| `ApiUrl` | Base URL for the app/REST API |
| `UserPoolId` / `UserPoolClientId` | Cognito config for the app login |
| `DevicesTableName` | DynamoDB table name |

Then get your MQTT endpoint (goes into firmware `secrets.h`):

```bash
aws iot describe-endpoint --endpoint-type iot:Data-ATS
```

## Provision a device

Each ESP32 needs its own IoT Thing + certificate. Use the helper:

```bash
./provision-device.sh ac-livingroom ./certs/ac-livingroom
```

This creates the Thing, generates a keypair + certificate, attaches the
`AcDevicePolicy`, and writes the PEM files to the output dir. Paste the cert,
private key, and the Amazon Root CA into `firmware/src/secrets.h`. Also create a
matching row in DynamoDB so the device shows up for your user:

```bash
aws dynamodb put-item --table-name <DevicesTableName> --item '{
  "deviceId": {"S":"ac-livingroom"},
  "ownerSub": {"S":"<your-cognito-sub>"},
  "name": {"S":"Living Room AC"}
}'
```

## Cost

≈ **$0.10–0.20/month per device** (often effectively $0 under the free tier).
Telemetry is written to DynamoDB directly by an IoT Rule (no Lambda per message),
the firmware publishes on-change + heartbeat (not every sample), Lambdas are
ARM64 with 1-week log retention, and there's no always-on compute or NAT gateway.
A built-in **AWS Budget alert** protects against surprise bills.

Full breakdown, the EC2/Timestream comparison, and tuning knobs:
[`../docs/COST.md`](../docs/COST.md).

## Lambda local notes

`lambdas/api` and `lambdas/ingest` are zero-dependency (they use the AWS SDK v3
bundled in the Node 20 runtime), so there's no build step — CDK zips the folder
as-is.
