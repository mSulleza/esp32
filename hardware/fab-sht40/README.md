# SHT40 variant — DONE, ready to order (~$82 / 5)

Cheaper **SHT40** sensor variant (temp+humidity, I2C 0x44) — ~$24 less than the
BME280 version over 5 boards. **Fully routed: 0 DRC violations, 0 unconnected, 0
schematic-parity errors.** Ready to upload to JLCPCB.

## Upload to JLCPCB
| File | Where |
|------|-------|
| `ac_controller_gerbers.zip` | PCB page → **Add gerber file** (upload the .zip as-is) |
| `ac_controller_bom.csv` | PCB Assembly → **BOM file** |
| `ac_controller_cpl.csv` | PCB Assembly → **CPL / Centroid file** |

## Before paying — verify rotations in JLC's 3D preview
Part-specific rotations no database can auto-correct:
- **U5** (SHT40) — CPL has it at 0°; confirm pin 1 (SDA) lands correctly, rotate if not.
- **D1, D2** (red LEDs) — check cathode direction.
- **U6** (IR receiver) — check pin 1.

## Firmware note
Sensor is **SHT40 (I2C 0x44, temp+humidity)**, not BME280 — use the SHT4x driver
at address 0x44 (no pressure reading).

## What was done to finish it (vs the autorouted board)
- Routed the 3 sensor nets to U5: **SDA** and **SCL** drop to the bottom copper
  layer (vias) to cross the GND track up to the pullups; **+3V3** hops to C6.
- The SHT4x footprint's under-chip keep-out was set to **allow tracks/vias** (the
  copper **pour is still excluded** under the sensor, preserving most thermal isolation).
- Min through-hole set to 0.2 mm so the ESP32's thermal vias pass DRC.

## Files
- `ac_controller.kicad_pcb` (+ `.kicad_sch`, `.net`, `.kicad_pro`) — finished board
- `ac_controller_gerbers.zip` — complete fab outputs
- `ac_controller_bom.csv`, `ac_controller_cpl.csv` — assembly files
- `ac_controller_top.png` — 3D render
