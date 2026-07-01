# DEV Wiring — IR Emitter + Receiver on an ESP32 Dev Board

A **minimal breadboard/dev wiring** for bring-up: just the **IR transmit** (emitter
diode + driver) and **IR receive** (receiver module) circuits hung off an
**ESP32 DevKit v1** (or any ESP32 dev board with onboard USB).

> **Why this doc is short:** the dev board already integrates everything in the
> programming chain — USB-UART bridge (CH340/CP2102), the 3.3 V regulator, and the
> DTR/RTS auto-program reset. So nothing from `hardware/SCHEMATIC.md` (U1 ESD,
> U2 LDO, U3 CH340C, Q1/Q2 auto-reset, USB-C J1) is needed. You only add the two
> IR circuits below. The BME280 is intentionally omitted — add it later from
> `docs/HARDWARE.md` § 3c if you want temperature/humidity.

---

## Pin map (only the IR pins)

| Signal | ESP32 GPIO | Direction | Connects to |
|--------|-----------|-----------|-------------|
| IR transmit | **GPIO4**  | output | 1 kΩ → transistor base (RMT-capable pin) |
| IR receive  | **GPIO14** | input  | IR receiver `OUT` |

Power taps off the dev board: **VIN/5V** (USB pass-through, for the IR LED) and
**3V3** (onboard regulator, for the IR receiver). Common **GND**.

---

## Wiring diagram

```
                         ESP32 DevKit v1
                  ┌──────────────────────────┐
   USB ──(power)─►│ [USB]              3V3 ●──┼──────────────┬───────── +3.3V rail
                  │                     5V ●──┼────────┐     │
                  │                    GND ●──┼──┐     │     │
                  │                            │  │     │     │
                  │             GPIO4 (TX) ●───┼┐ │     │     │
                  │             GPIO14(RX) ●───┼┼─┼──┐  │     │
                  └────────────────────────────┘│ │  │  │     │
                                                 │ │  │  │     │
   ── IR TRANSMIT (5 V, pulsed via transistor) ──┘ │  │  │     │
                                                   │  │  │     │
                       +5V ─────[47 Ω]──► A        │  │  │     │
                                       (IR LED 940nm)  │  │     │
                                          K            │  │     │
                                          │ collector  │  │     │
                                   ┌──────┴──────┐     │  │     │
        GPIO4 ──[1 kΩ]──── base ───┤  2N2222 NPN │     │  │     │
                                   └──────┬──────┘     │  │     │
                                          │ emitter    │  │     │
                            GND ──────────┴────────────┘  │     │
                                                          │     │
   ── IR RECEIVE (VS1838B / TSOP38238, runs at 3.3 V) ────┘     │
                                                                │
        +3.3V ──[100 Ω]──┬───────────── VCC                     │
                         │                  (front view:        │
                      [4.7 µF]               OUT  GND  VCC )     │
                         │                                       │
        GND ─────────────┴───────────── GND                      │
                                        OUT ──────► GPIO14 ●─────┘
```

Two separate supply rails — note the IR **LED** is fed from **5 V**, the IR
**receiver** from **3.3 V**. They share GND with the ESP32.

---

## IR transmit (emitter) — detail

```
   +5V (VIN) ───────────┐
                        │
                      ┌─┴─┐   IR LED 940 nm
                      │ ▲ │   anode (A) to 5 V side
                      └─┬─┘
                        │
                      [47 Ω]      ← current limit, ONE per LED
                        │
                        │  collector
                  ┌─────┴─────┐
   GPIO4 ─[1 kΩ]──┤ B  2N2222 │   NPN (PN2222 / BC547 also fine)
                  │    (NPN)   │
                  └─────┬─────┘
                        │  emitter
                       GND
```

- The GPIO switches the transistor **base** through 1 kΩ; the transistor sinks the
  LED to GND. The 38 kHz carrier (~33 % duty) comes from the ESP32 **RMT**
  peripheral, so average current stays low even with the small series resistor.
- **More range:** add a second IR LED in **parallel, each with its own 47 Ω**
  (never share one resistor), or drop to 33 Ω and use a logic-level MOSFET
  (2N7000 / IRLZ44N) instead of the 2N2222.
- The IR LED is **clear/water-white** and looks identical to the receiver dome —
  keep them labelled. Point it at the AC's IR window; a wall/ceiling bounce works
  for short rooms.

## IR receive — detail

```
   +3.3V ──[100 Ω]──┬──────── VCC (pin 3)
                    │
                 [4.7 µF]              VS1838B / TSOP38238
                    │                  (front view: OUT GND VCC)
   GND ─────────────┴──────── GND (pin 2)
                              OUT (pin 1) ─────► GPIO14
```

- Power the receiver from **3.3 V** so its push-pull `OUT` swings 0–3.3 V, inside
  the ESP32 input range — **do not** run it at 5 V into a GPIO.
- The **100 Ω + 4.7 µF** is the datasheet supply filter; it noticeably improves
  decode reliability. Keep the cap close to the module.
- The IR receiver is the **dark/tinted dome** module (38 kHz demodulator), not a
  bare photodiode. Pinout varies by vendor — **confirm OUT/GND/VCC** against the
  marking before wiring.

---

## Mini bill of materials (dev setup)

| # | Part | Qty | Notes |
|---|------|-----|-------|
| 1 | ESP32 DevKit v1 (or any USB ESP32 dev board) | 1 | Programming/power already onboard |
| 2 | IR LED 940 nm (through-hole 5 mm) | 1–2 | Emitter; 2 in parallel widens coverage |
| 3 | VS1838B / TSOP38238 IR receiver module | 1 | 38 kHz demodulator, 3-pin |
| 4 | 2N2222 NPN transistor (or 2N7000 MOSFET) | 1 | IR LED driver |
| 5 | Resistor 1 kΩ | 1 | Transistor base |
| 6 | Resistor 47 Ω (¼ W) | 1–2 | IR LED current limit (one per LED) |
| 7 | Resistor 100 Ω | 1 | IR receiver supply filter |
| 8 | Capacitor 4.7 µF electrolytic | 1 | IR receiver supply decoupling |
| 9 | Breadboard + jumper wires | — | |

Firmware pins already match: **GPIO4 = IR TX**, **GPIO14 = IR RX** (see
`docs/HARDWARE.md` § 2 and the firmware config).

---

## Bring-up (IR only)

1. Power the dev board over USB; confirm it enumerates and the serial monitor
   shows boot logs.
2. Wire the **IR receiver**. Enter capture/learn mode, press an AC-remote button,
   and confirm the serial log prints a decoded protocol or raw timing.
3. Wire the **IR transmitter**. Replay a captured "power" code at the AC and verify
   it responds. Poor range? See *IR transmit — detail* above.
4. (Optional) Add the BME280 per `docs/HARDWARE.md` § 3c.

> Quick test that the IR LED pulses at all: most phone cameras (front camera
> especially) show the 940 nm LED as a faint purple/white flicker when it fires.
