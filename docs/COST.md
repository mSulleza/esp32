# Cost Efficiency

This design is **serverless and scales toward zero** — there is no always-on
server, no NAT gateway, and no Timestream/Kinesis. For a home deployment the
steady-state cost is **a few cents per month per device**. This doc shows where
every cent goes, the optimizations applied, and how to stay protected from
surprise bills.

## TL;DR

| Lever | Choice | Why |
|-------|--------|-----|
| Compute | Lambda (not EC2) | No fixed monthly cost; pay per request, idles free |
| Telemetry path | IoT Rule → DynamoDB **direct** | No Lambda invoke per message |
| Telemetry volume | Delta + 10-min heartbeat | ~5–10× fewer messages/writes than fixed 30 s |
| Lambda | ARM64 (Graviton), 128–256 MB | ~20% cheaper compute |
| Logs | 1-week CloudWatch retention | Stops the classic silent log-storage bill |
| Telemetry storage | DynamoDB TTL 30 days | Auto-purge; no unbounded growth |
| Networking | No VPC / no NAT gateway | Avoids the single biggest avoidable cost (~$32/mo) |
| Guardrail | AWS Budget alert | Surfaces any misconfig before it's expensive |

## Estimated monthly cost — 1 device

Assumes the optimized firmware: BME280 sampled every 30 s but **published only on
a ≥0.3 °C / ≥2 %RH change or every 10 min**. Realistic average ≈ **1 publish/min**
(rooms are stable for long stretches; busier during AC ramp). Call it
~45,000 telemetry messages/month, plus light command/state traffic.

| Service | Usage | Est. cost |
|---------|-------|-----------|
| IoT Core — connectivity | 1 device, persistent | ~$0.004 |
| IoT Core — messaging | ~45k msgs (5 KB units) | ~$0.05 |
| IoT Core — rules engine | ~45k triggers | ~$0.01 |
| DynamoDB — writes (on-demand) | ~45k writes, <1 KB | ~$0.06 |
| DynamoDB — storage | ~7 MB (30-day TTL) | ~$0.00 |
| Lambda (api + low-vol ingest) | hundreds of invokes | ~$0.00 (free tier) |
| API Gateway HTTP API | app calls | ~$0.00 (free tier) |
| Cognito | 1 user | $0.00 |
| CloudWatch Logs | 1-week retention | ~$0.01 |
| **Total** | | **≈ $0.10–0.20 / month** |

> Most of these fall under the AWS perpetual free tier for a single household, so
> real-world bills are often effectively **$0** for the first device and a few
> cents each beyond.

## Why not the alternatives

- **EC2 + Mosquitto + always-on API** (the other backend option): a `t4g.small`
  is ~$12/mo *fixed*, running 24/7 whether or not the AC is used. This serverless
  design is ~50–100× cheaper at home scale. EC2 only wins at very high, constant
  message volume.
- **Amazon Timestream** for history: has per-GB ingestion + memory-store costs
  that exceed DynamoDB-with-TTL at this tiny volume. Skipped. (Worth it only if
  you later want years of fine-grained analytics — then write to **S3 + Athena**,
  which is cheaper than Timestream for cold data.)
- **Lambda per telemetry message**: removed. Telemetry now writes to DynamoDB via
  a native IoT Rule action, so there's no invoke/cold-start per reading.

## The real risk: surprise bills, not steady state

Steady-state cost is trivial. The thing that actually bites people is a
**misconfiguration** (a runaway loop publishing thousands of msgs/sec, a
mis-scoped resource, accidentally enabling an expensive service). Two defenses
are built in:

1. **AWS Budget alert** — set `BUDGET_ALERT_EMAIL` (and optionally
   `MONTHLY_BUDGET_USD`, default `5`) before `cdk deploy`. You get an email at
   80% forecast and 100% actual. Costs nothing.
   ```bash
   export BUDGET_ALERT_EMAIL=mark@example.com
   export MONTHLY_BUDGET_USD=5
   npx cdk deploy
   ```
2. **Bounded telemetry** — the firmware delta + heartbeat logic caps how often a
   device can publish even if the sensor reading is noisy.

## Going for literal $0 (optional)

DynamoDB's **always-free tier** is 25 GB + 25 WCU + 25 RCU (provisioned mode).
Our write rate (~0.02 writes/s avg) is far below 25 WCU. If you switch the tables
from `PAY_PER_REQUEST` to **provisioned** capacity (e.g. 5 WCU / 5 RCU with
autoscaling), DynamoDB becomes free under that allotment — at the cost of a small
throttle risk on bursts and the allotment being shared across your whole account.
For one or two devices, on-demand's pennies aren't worth that complexity, so it's
left as on-demand by default. Flip it in `lib/ac-backend-stack.ts` if you want.

## Knobs to tune cost vs responsiveness (firmware `config.h`)

| Constant | Default | Effect |
|----------|---------|--------|
| `SENSOR_SAMPLE_MS` | 30 s | How often the BME280 is read (no cloud cost) |
| `TELEMETRY_HEARTBEAT_MS` | 10 min | Max time between forced publishes |
| `TELEMETRY_DELTA_TEMP` | 0.3 °C | Smaller = more publishes = more cost |
| `TELEMETRY_DELTA_HUM` | 2 %RH | Smaller = more publishes = more cost |

Raising the heartbeat to 30 min and widening the deltas cuts cost further if you
don't need fine-grained history. Commands and schedules are unaffected — they're
event-driven and effectively free.
