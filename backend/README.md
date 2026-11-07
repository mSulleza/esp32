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

# Optional: browser origins allowed to call the API (CORS). Default: none.
# npx cdk deploy -c corsOrigins=http://localhost:5173,https://app.example.com
npx cdk deploy
```

### CORS (browser origins)

The HTTP API sends CORS headers only for the origins you list. With nothing set
(the default) no browser page can call the API cross-origin; curl, native apps
and server-side callers are unaffected. Set a comma-separated list either way:

```bash
npx cdk deploy -c corsOrigins=http://localhost:5173,https://app.example.com
# or
export CORS_ALLOWED_ORIGINS=http://localhost:5173,https://app.example.com
```

or permanently in `cdk.json` under `"context": { "corsOrigins": [...] }`. Each
entry must be a bare origin (`https://host[:port]`, no path); a `*` wildcard is
refused at synth time.

Outputs printed on success:

| Output | Use |
|--------|-----|
| `ApiUrl` | Base URL for the app/REST API |
| `UserPoolId` / `UserPoolClientId` | Cognito config for the app login |
| `DevicesTableName` | DynamoDB table name |

## Create app users

Self sign-up is **disabled**: a Cognito user can call the API, so only accounts
you create can sign in. Create one (Cognito emails a temporary password; the
user sets a new one at first sign-in):

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <UserPoolId> \
  --username you@example.com \
  --user-attributes Name=email,Value=you@example.com Name=email_verified,Value=true
```

Their `sub` (needed to provision a device for them):

```bash
aws cognito-idp admin-get-user --user-pool-id <UserPoolId> --username you@example.com \
  --query "UserAttributes[?Name=='sub'].Value" --output text
```

Then get your MQTT endpoint (goes into firmware `secrets.h`):

```bash
aws iot describe-endpoint --endpoint-type iot:Data-ATS
```

## Provision a device

Each ESP32 needs its own IoT Thing + certificate **and** an owned row in the
`Devices` table. Use the helper (from `backend/cdk`):

```bash
./provision-device.sh ac-livingroom ./certs/ac-livingroom <owner-cognito-sub> "Living Room AC"
```

This first writes the `Devices` row `{deviceId, ownerSub, name}` (refusing to
overwrite an existing row, so a device can't be re-assigned by re-running it),
then creates the Thing, generates a keypair + certificate, attaches the
`AcDevicePolicy`, and writes the PEM files to the output dir (mode 600). The
table name comes from the stack outputs; set `DEVICES_TABLE` to override. Paste
the cert, private key, and the Amazon Root CA into `firmware/src/secrets.h`.

The `Devices` row is the only way a device gets an owner:

- the **api** Lambda serves a device only to the Cognito user whose `sub` equals
  the row's `ownerSub` (a row with no owner is served to nobody), and
- the **ingest** Lambda only *updates* existing rows (`attribute_exists(deviceId)`);
  a check-in from a Thing without a row is logged and dropped, never creates one.

To hand a device to someone else, update `ownerSub` on its row directly.

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
