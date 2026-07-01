# API & Message Contracts

This document defines (1) the MQTT topics between device and AWS IoT Core, (2) the
Device Shadow document, and (3) the REST API exposed to the app via API Gateway.

All timestamps are epoch **milliseconds** unless noted. `{id}` = device/Thing id.

---

## 1. MQTT topics (device ↔ AWS IoT Core)

### `ac/{id}/telemetry` — device → cloud (QoS 0, ~every 30 s)
```json
{
  "ts": 1718000000000,
  "tempC": 26.4,
  "humidity": 58.2,
  "pressure": 1009.1,
  "rssi": -61,
  "timeSynced": true
}
```

### `ac/{id}/state` — device → cloud (on change)
Reported current AC state as the device believes it to be.
```json
{
  "ts": 1718000000000,
  "power": true,
  "mode": "cool",
  "tempC": 24,
  "fan": "auto",
  "swing": "off",
  "protocol": "DAIKIN",
  "source": "schedule"
}
```
`source` ∈ `manual | schedule | command | learn`.

### `ac/{id}/captured` — device → cloud (during learn mode)
```json
{
  "ts": 1718000000000,
  "label": "power_on",
  "decoded": { "protocol": "GREE", "power": true, "mode": "cool", "tempC": 25, "fan": "high" },
  "raw": { "freqKhz": 38, "timings": [9000,4500,560,560, "..."] }
}
```
`decoded` is `null` if the protocol was not recognised; `raw` is always present.

### `ac/{id}/command` — cloud → device (QoS 1)
```json
{ "cmd": "setState",  "reqId": "uuid", "state": { "power": true, "mode": "cool", "tempC": 23, "fan": "med" } }
{ "cmd": "replay",    "reqId": "uuid", "rawCodeId": "power_on" }
{ "cmd": "capture",   "reqId": "uuid", "enable": true, "label": "power_on", "timeoutSec": 30 }
{ "cmd": "identify",  "reqId": "uuid" }            // blink LED to locate device
{ "cmd": "getState",  "reqId": "uuid" }
```

### `ac/{id}/schedules` — cloud → device (full replace)
```json
{
  "ts": 1718000000000,
  "schedules": [
    { "id": "sch_morning", "enabled": true, "daysOfWeek": [1,2,3,4,5],
      "time": "07:30", "action": { "power": true, "mode": "cool", "tempC": 24, "fan": "auto" }, "rawCodeId": null }
  ]
}
```

### `ac/{id}/ack` — device → cloud
```json
{ "reqId": "uuid", "ok": true, "ts": 1718000000000, "detail": "setState applied" }
```

---

## 2. Device Shadow (classic)

Mirrors AC state so the app gets desired/reported/delta for free.
```json
{
  "state": {
    "desired":  { "power": true, "mode": "cool", "tempC": 23, "fan": "med" },
    "reported": { "power": true, "mode": "cool", "tempC": 24, "fan": "auto",
                  "online": true, "fwVersion": "1.0.0" }
  }
}
```
The device subscribes to `$aws/things/{id}/shadow/update/delta`, applies the delta
via IR, then reports the new state. The API writes `desired` to set state when the
device may be offline (it reconciles on reconnect).

---

## 3. REST API (API Gateway HTTP API → Lambda)

Base: `https://{api-id}.execute-api.{region}.amazonaws.com`
Auth: `Authorization: Bearer <Cognito JWT>` on every route.

| Method & path | Purpose |
|---------------|---------|
| `GET    /devices` | List devices owned by the caller |
| `GET    /devices/{id}` | Device detail incl. last state & protocol |
| `POST   /devices/{id}/command` | Send a command (body = a `command` payload from §1) |
| `GET    /devices/{id}/telemetry?from=&to=` | Time-series temp/humidity |
| `GET    /devices/{id}/codes` | List learned IR code labels |
| `POST   /devices/{id}/capture` | Start/stop learn mode `{ "enable": true, "label": "power_on" }` |
| `GET    /devices/{id}/schedules` | List schedules |
| `PUT    /devices/{id}/schedules` | Replace full schedule list (triggers device sync) |
| `POST   /devices/{id}/schedules` | Create one schedule |
| `DELETE /devices/{id}/schedules/{sid}` | Delete a schedule |

### Example: set state
```
POST /devices/ac-livingroom/command
{ "cmd": "setState", "state": { "power": true, "mode": "cool", "tempC": 23, "fan": "med" } }
```
→ `202 { "reqId": "…", "delivered": true }` (published to `ac/{id}/command` and
written to the device shadow `desired`).

### Example: create schedule
```
POST /devices/ac-livingroom/schedules
{ "enabled": true, "daysOfWeek": [1,2,3,4,5], "time": "07:30",
  "action": { "power": true, "mode": "cool", "tempC": 24, "fan": "auto" } }
```
→ `201 { "scheduleId": "sch_…" }`, then the backend re-publishes the full list to
`ac/{id}/schedules`.

---

## 4. Enumerations

- **mode:** `cool | heat | dry | fan | auto`
- **fan:** `auto | low | med | high | max` (mapped per protocol by `IRac`)
- **swing:** `off | vertical | horizontal | both`
- **daysOfWeek:** array of `0–6`, `0 = Sunday`
