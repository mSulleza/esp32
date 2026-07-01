# System Design

## 1. Goals

- **Capture** IR codes from any AC remote (learn mode).
- **Send** IR commands to drive the AC: power, mode (cool/heat/dry/fan/auto),
  target temperature, fan speed, swing.
- **Sense** room temperature & humidity (BME280).
- **Schedule** actions locally on the device so they fire even when offline.
- **Connect** to an AWS backend for remote control, telemetry history, and
  schedule management.

## 2. Component overview

```
┌──────────────────────── ESP32 firmware ────────────────────────┐
│                                                                 │
│  SensorTask ──► reads BME280 every N s ──► telemetry buffer     │
│                                                                 │
│  IrManager  ──► IRrecv (learn)  + IRsend / IRac (send)          │
│                                                                 │
│  ScheduleEngine ─► checks NTP local time each minute,           │
│                    fires matching schedules via IrManager       │
│                                                                 │
│  Cloud (MQTT/TLS) ─► AWS IoT Core: pub telemetry/state/captured │
│                       sub commands/schedules                    │
│                                                                 │
│  StateStore (NVS) ─► persists AC state, learned codes,          │
│                       schedules, device config                  │
└─────────────────────────────────────────────────────────────────┘
                                 │ MQTT/TLS (X.509)
                                 ▼
┌──────────────────────────── AWS ────────────────────────────────┐
│  IoT Core (broker + Device Shadow)                               │
│    └─ IoT Rules ─► Lambda(ingest) ─► DynamoDB (Telemetry)        │
│  API Gateway (HTTP API) ─► Lambda(api) ─► DynamoDB               │
│                                  └─► IoT publish (commands)       │
│  Lambda(schedule-sync) ─► pushes schedule changes to device      │
│  DynamoDB: Devices, Schedules, Telemetry                         │
│  Cognito (user auth for the app/API)                             │
└──────────────────────────────────────────────────────────────────┘
```

## 3. Generic / multi-brand strategy

You chose **multiple / generic** AC support. The firmware uses
[`IRremoteESP8266`](https://github.com/crankyoldgit/IRremoteESP8266), which gives
us two complementary paths:

1. **Decoded protocol path (preferred).** On capture, `IRrecv` tries to decode
   the burst. If it recognises a supported A/C protocol (Daikin, Mitsubishi,
   Gree, Fujitsu, Panasonic, LG, Coolix, and ~50 more), we store the **decoded
   semantic state** (brand + power/mode/temp/fan). Sending then uses the `IRac`
   helper, which rebuilds a valid frame for *any* temp/mode/fan combination —
   so you can set 23°C even if you never pressed "23" on the remote.

2. **Raw replay path (fallback).** If the protocol is unknown/undecoded, we store
   the **raw mark/space timing array** for each button you press in learn mode
   and replay it verbatim. This works with any remote but only reproduces the
   exact buttons you captured (no interpolation).

The device records *which* path a given AC uses in its config and reports the
detected protocol to the backend, so the app can show either a full control
panel (decoded) or a fixed button grid (raw).

> **Stateful remotes:** most AC remotes are *stateful* — each press transmits the
> entire desired state, not a delta. `IRac` models this correctly; for raw mode
> we capture each full-state button. This is why "learn every button you care
> about" matters for raw-mode ACs.

## 4. Device ↔ cloud message contracts

All topics are namespaced by `deviceId` (the IoT Thing name). Payloads are JSON.
Full schemas in [`API.md`](API.md). Summary:

| Topic | Dir | Purpose |
|-------|-----|---------|
| `ac/{id}/telemetry`  | dev → cloud | temp, humidity, pressure, rssi, ts |
| `ac/{id}/state`      | dev → cloud | reported AC state (power/mode/temp/fan) |
| `ac/{id}/captured`   | dev → cloud | a newly-learned IR code (decoded or raw) |
| `ac/{id}/command`    | cloud → dev | setState / capture / replay / identify |
| `ac/{id}/schedules`  | cloud → dev | full schedule list sync |
| `ac/{id}/ack`        | dev → cloud | command/schedule acknowledgements |

We **also** mirror power/mode/temp/fan into the **AWS IoT Device Shadow** so the
app can read "last known + desired" state with built-in delta handling. Topics
above are used for events and learning that don't fit the shadow model.

## 5. Schedule model

A schedule fires a target AC state at given local times. Stored in DynamoDB,
synced to the device, cached in NVS, evaluated on-device against NTP time.

```jsonc
{
  "id": "sch_morning",
  "enabled": true,
  "daysOfWeek": [1,2,3,4,5],     // 0=Sun … 6=Sat
  "time": "07:30",               // local time (device TZ)
  "action": {                    // a target AC state (decoded mode)
    "power": true, "mode": "cool", "tempC": 24, "fan": "auto"
  },
  "rawCodeId": null,             // OR replay a learned raw code instead
  "updatedAt": 1718000000
}
```

**Evaluation:** the `ScheduleEngine` wakes once per minute, computes local
`HH:MM` + weekday from NTP-synced time, and fires any enabled schedule whose
`time` and `daysOfWeek` match and that hasn't already fired this minute. Firing
applies `action` via `IRac` (or replays `rawCodeId`), updates state, and emits an
`ack`. Because schedules live in NVS and time comes from NTP (with a last-known
fallback), schedules keep firing through a cloud/internet outage.

**Time zone:** device stores an IANA-ish offset/rule from config; for DST-aware
behaviour set the POSIX `TZ` string in config (e.g. `SGT-8` for Singapore, no
DST). NTP via `pool.ntp.org`.

## 6. Data model (DynamoDB)

Single-region, on-demand capacity. Three tables (or one single-table design —
kept separate here for clarity):

**`Devices`** — PK `deviceId`
```
deviceId, ownerSub, name, protocol, supportsDecoded(bool),
lastState{...}, lastSeen, fwVersion, tzString
```

**`Schedules`** — PK `deviceId`, SK `scheduleId`
```
deviceId, scheduleId, enabled, daysOfWeek, time, action{...},
rawCodeId, updatedAt
```

**`Telemetry`** — PK `deviceId`, SK `ts` (epoch ms); TTL attribute `expireAt`
```
deviceId, ts, tempC, humidity, pressure, rssi
```
Telemetry rows auto-expire via DynamoDB TTL (e.g. 90 days). For long-term
analytics, an IoT Rule can additionally fan telemetry to Amazon Timestream or
S3 — left as an optional extension.

**Learned IR codes** are stored on-device in NVS (they're large raw arrays) and a
copy is pushed to the backend in `Devices` (or an S3 object per device) for
backup/restore, so a re-flashed device can re-download its code library.

## 7. Security

- **Device → cloud:** mutual TLS with a per-device X.509 certificate issued by
  AWS IoT. The IoT **policy** is scoped so a device may only pub/sub on its own
  `ac/{thingName}/*` topics and its own shadow (using IoT policy variables like
  `${iot:Connection.Thing.ThingName}`).
- **App/API → cloud:** API Gateway HTTP API protected by a **Cognito** JWT
  authorizer; Lambda checks the caller owns the `deviceId`.
- Secrets (Wi-Fi creds, certs) live in `firmware/src/secrets.h` (git-ignored) and
  are flashed into the device; never commit them.

## 8. Failure & edge handling

| Scenario | Behaviour |
|----------|-----------|
| Wi-Fi / cloud down | Device keeps sensing + firing cached schedules; buffers telemetry (ring buffer) and re-publishes on reconnect |
| NTP unavailable at boot | Uses last-known time from RTC memory; schedules resume once NTP syncs; flags "time unsynced" in telemetry |
| Unknown AC protocol | Falls back to raw capture/replay; reports `supportsDecoded=false` |
| Command for offline device | API writes desired state to Device Shadow; device reconciles on reconnect |
| Conflicting schedule + manual | Last write wins; manual commands always take effect immediately |

## 9. Roadmap / extensions

- OTA firmware updates via AWS IoT Jobs.
- Timestream + Grafana / QuickSight dashboards for temp/humidity trends.
- "Eco" closed-loop control: hold a target room temp using BME280 feedback
  rather than fixed AC setpoint.
- Multiple AC units per device (multiple IR LEDs / aimed emitters).
- Home Assistant / Matter bridge.
