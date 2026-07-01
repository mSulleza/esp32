# Hardware — Wiring, Schematic & Bill of Materials

This document covers the full electrical design: the bill of materials, the GPIO
pin map, the IR transmit driver circuit, the IR receive circuit, the BME280
sensor connection, and power.

> ⚠️ **Why you can't just wire an IR LED to a GPIO:** an ESP32 GPIO sources only
> ~12–40 mA and idles at 3.3 V. An IR LED pulsed for remote-control range wants
> 100 mA+ peaks. We therefore drive the IR LED from the 5 V rail through a
> **transistor** switched by the GPIO. The IR *receiver* is an active module
> (demodulator) and connects directly.

---

## 1. Bill of materials

| # | Part | Qty | Notes |
|---|------|-----|-------|
| 1 | **ESP32 DevKit v1** (38-pin, WROOM-32) | 1 | Any ESP32 dev board with USB works |
| 2 | **BME280** breakout (I²C) | 1 | Temp + humidity (+ pressure). Confirm I²C, not SPI-only |
| 3 | **VS1838B / TSOP38238** IR receiver module | 1 | 38 kHz demodulator, 3-pin. For *learning* the remote |
| 4 | **IR LED 940 nm** | 1–2 | Two in parallel (each own resistor) widens coverage |
| 5 | **2N2222** NPN transistor (or 2N7000 MOSFET) | 1 | IR LED driver |
| 6 | Resistor **1 kΩ** | 1 | Transistor base resistor |
| 7 | Resistor **47 Ω** (¼ W) | 1–2 | IR LED current limit (one per LED) |
| 8 | Resistor **100 Ω** | 1 | IR receiver supply filter (per datasheet) |
| 9 | Capacitor **4.7 µF** electrolytic | 1 | IR receiver supply decoupling |
| 10 | Capacitor **0.1 µF** ceramic | 2 | Decoupling for ESP32 / sensor rails |
| 11 | Breadboard or perfboard + jumper wires | — | |
| 12 | 5 V USB supply (≥1 A) | 1 | Powers the board via USB |

**Approx cost:** ~US$12–18 total.

---

## 2. Pin map (ESP32 DevKit v1)

| Signal | ESP32 GPIO | Direction | Connects to |
|--------|-----------|-----------|-------------|
| IR transmit | **GPIO4**  | output | Base resistor → transistor (RMT-capable pin) |
| IR receive  | **GPIO14** | input  | IR receiver `OUT` |
| I²C SDA     | **GPIO21** | bidir  | BME280 `SDA` |
| I²C SCL     | **GPIO22** | bidir  | BME280 `SCL` |
| Status LED  | **GPIO2**  | output | On-board LED (boot/Wi-Fi/activity) |
| Capture button (optional) | **GPIO0** | input | Push-to-GND, enters learn mode (also boot strap pin — only read after boot) |

Pins chosen to avoid flash pins (6–11) and to keep IR TX on an RMT-capable pin.
GPIO34/35/36/39 are input-only — fine for the IR receiver if you prefer, but
GPIO14 keeps things simple and supports interrupts.

---

## 3. Schematic (ASCII)

```
                              ESP32 DevKit v1
                       ┌───────────────────────────┐
   5V USB ───────────► │ 5V (VIN)             3V3   │ ──► 3.3 V rail
                       │                            │
                       │ GND ───────────── GND rail │
                       │                            │
       ┌────────────── │ GPIO4 (IR TX)              │
       │               │                            │
       │               │ GPIO14 (IR RX) ◄────────┐  │
       │               │                         │  │
       │               │ GPIO21 (SDA) ◄────────┐ │  │
       │               │ GPIO22 (SCL) ◄──────┐ │ │  │
       │               └─────────────────────┼─┼─┼──┘
       │                                      │ │ │
       │  IR TRANSMIT (high-current, pulsed)  │ │ │
       │                                      │ │ │
       │   GPIO4 ──[1kΩ]──┐ base              │ │ │
       │                  │                   │ │ │
       │            2N2222 │ NPN               │ │ │
       │      collector ───┤                   │ │ │
       │            │      │ emitter           │ │ │
       │   5V ─[47Ω]─▼     └──── GND           │ │ │
       │        IR LED ▼ (940nm)               │ │ │
       │       (cathode→collector)             │ │ │
       │                                       │ │ │
       │  IR RECEIVE (VS1838B / TSOP38238)     │ │ │
       │                                       │ │ │
       │   3V3 ──[100Ω]──┬──── VCC             │ │ │
       │                 │                     │ │ │
       │              [4.7µF]                  │ │ │
       │                 │                     │ │ │
       │   GND ──────────┴──── GND             │ │ │
       │                       OUT ────────────┘ │ │
       │                                         │ │
       │  BME280 (I²C)                           │ │
       │   3V3 ──── VCC                          │ │
       │   GND ──── GND                          │ │
       │   SDA ─────────────────────────────────┘ │
       │   SCL ───────────────────────────────────┘
       │
       └─ (5V rail)
```

### 3a. IR transmit driver (detail)

```
   5V ──────────────┐
                    │
                  ┌─┴─┐  IR LED (940 nm), anode to 5V
                  │ ▲ │
                  └─┬─┘
                    │
                  [47 Ω]      ← current limit (one per LED)
                    │
                    │  collector
              ┌─────┴─────┐
   GPIO4 ─[1kΩ]─┤ B   2N2222 │   NPN, e.g. PN2222 / BC547
              │   (NPN)   │
              └─────┬─────┘
                    │  emitter
                   GND
```

- The GPIO drives the **base** through 1 kΩ; the transistor switches the LED to
  ground. The IR carrier (38 kHz, ~33% duty) is generated by the ESP32 RMT
  peripheral, so average current stays low even with a small series resistor.
- **More range?** Add a second IR LED in parallel, *each with its own 47 Ω
  resistor*, or drop to 33 Ω and use a logic-level MOSFET (2N7000 / IRLZ44N)
  instead of the 2N2222. Don't share one resistor between two LEDs.
- Point the IR LED toward where the AC's IR window is. Bounce off a wall/ceiling
  also works for short rooms.

### 3b. IR receive (detail)

```
   3V3 ──[100Ω]──┬──────── VCC (pin 3)
                 │
              [4.7µF]                VS1838B / TSOP38238
                 │                   (front view: OUT GND VCC)
   GND ──────────┴──────── GND (pin 2)
                           OUT (pin 1) ──────► GPIO14
```

- Power the receiver from **3.3 V** so its push-pull `OUT` swings 0–3.3 V and
  stays within the ESP32's input range (don't run it at 5 V into a GPIO).
- The 100 Ω + 4.7 µF form the supply filter recommended in the datasheet — they
  noticeably improve decode reliability. Keep the cap close to the module.

### 3c. BME280

- Pure I²C: `VCC`→3V3, `GND`→GND, `SDA`→GPIO21, `SCL`→GPIO22.
- Most breakouts include 4.7 kΩ pull-ups on SDA/SCL — if yours doesn't, add
  them to 3.3 V. Default I²C address is `0x76` (some boards `0x77`).
- Mount the sensor **away from** the ESP32 regulator and the AC's airflow path so
  it reads room conditions, not self-heating. A short flying lead helps.

---

## 4. Power

- Board is powered from a **5 V / ≥1 A USB supply**. The on-board regulator
  produces the 3.3 V rail for the ESP32, BME280, and IR receiver.
- The IR LED draws from **5 V (VIN)**, not 3.3 V — keep that wire short and
  thick-ish; pulsed current peaks are what give range.
- Add a 0.1 µF ceramic across the ESP32 3V3/GND and another across the BME280 to
  tame Wi-Fi current spikes.

---

## 5. Bring-up checklist

1. Power only the ESP32 first; confirm it enumerates over USB and the serial
   monitor shows boot logs.
2. Add the BME280 — run an I²C scan (firmware logs the detected address at boot).
3. Add the IR **receiver** — enter capture mode, press a remote button, confirm
   the serial log prints a decoded protocol or raw timing.
4. Add the IR **transmitter** — replay a captured "power" code at the AC and
   verify it responds. If range is poor, see § 3a.
5. Verify the BME280 isn't being warmed by the board (compare to a reference
   thermometer); relocate on a lead if it reads high.
