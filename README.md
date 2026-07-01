# ESP32 Smart AC Controller

An IR-based smart controller for air conditioners. An ESP32 **learns** your AC
remote's IR codes, **replays** them to drive the AC (power / mode / temperature /
fan speed), reads **temperature & humidity** from a BME280 sensor, and fires
**schedules** locally even when the internet is down. Everything is connected to
an **AWS IoT Core + Lambda + DynamoDB** backend so you can control and schedule
it from anywhere.

```
   ┌──────────────┐        IR (38 kHz)        ┌──────────────┐
   │  AC Remote   │ ─────capture (learn)────► │              │
   └──────────────┘                           │    ESP32     │
   ┌──────────────┐                           │  Controller  │
   │ Air          │ ◄──────replay (send)───── │              │
   │ Conditioner  │                           │  + BME280    │
   └──────────────┘                           └──────┬───────┘
                                                      │ MQTT / TLS
                                                      ▼
                                    ┌─────────────────────────────────┐
                                    │   AWS IoT Core ── IoT Rules      │
                                    │      │            │              │
                                    │   Lambda  ──  DynamoDB           │
                                    │      │                           │
                                    │   API Gateway (HTTP API) ── App  │
                                    └─────────────────────────────────┘
```

## Repository layout

| Path | What's inside |
|------|---------------|
| `docs/DESIGN.md`   | System architecture, data flow, MQTT topics, data model |
| `docs/HARDWARE.md` | Breadboard/prototype wiring (dev-board + modules) for quick bring-up |
| `hardware/`        | **Orderable integrated PCB**: schematic, PCBA BOM (LCSC), layout + JLCPCB fab/order steps |
| `docs/API.md`      | REST API + MQTT topic + Device Shadow contracts |
| `docs/COST.md`     | Cost breakdown, optimizations, and the billing guardrail |
| `firmware/`        | PlatformIO ESP32 firmware (IR learn/send, sensor, schedules, MQTT) |
| `backend/cdk/`     | AWS CDK infrastructure (IoT Core, Lambda, DynamoDB, API Gateway) |
| `backend/lambdas/` | Lambda function source (API, command publisher, schedule sync) |

## Quick start

1. **Hardware** — build the circuit in [`docs/HARDWARE.md`](docs/HARDWARE.md).
2. **Backend** — `cd backend/cdk && npm install && npx cdk deploy`. Note the
   IoT endpoint and API URL it prints, and download the device certificate.
3. **Firmware** — copy `firmware/src/secrets.example.h` to `secrets.h`, fill in
   Wi-Fi + IoT endpoint + certificates, then `cd firmware && pio run -t upload`.
4. **Learn your remote** — put the device in capture mode (button or API), point
   your AC remote at the receiver, and press each button to store the codes.
5. **Control & schedule** — use the REST API / app to send commands and create
   schedules.

See each `docs/` file for full detail. Status: **reference design + working
skeleton** — protocol decoding for your specific AC may need tuning (see
`docs/DESIGN.md` § "Generic / multi-brand strategy").
