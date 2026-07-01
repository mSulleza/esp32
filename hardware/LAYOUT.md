# PCB Layout & Fab Spec

Target fab: **JLCPCB**, 2-layer, PCBA (economic/standard assembly). This doc gives
the stackup, design rules to load into KiCad, a placement plan, routing rules for
the three tricky nets, and the exact **Gerber + BOM + CPL export and ordering
steps**.

---

## Board

| Property | Value |
|----------|-------|
| Size | ~50 × 40 mm (fits the parts comfortably; shrink later) |
| Layers | 2 (top + bottom copper) |
| Thickness | 1.6 mm |
| Copper | 1 oz |
| Mounting holes | 4 × M3 (Ø3.2 mm) in corners, 3 mm edge inset |
| Assembly side | Top (all SMD on top → single-sided assembly = cheaper) |

Keep **all assembled SMD parts on the top layer** — JLCPCB charges more for
double-sided assembly, and there's no need here. Bottom layer = ground pour +
routing only.

---

## Stackup & JLCPCB 2-layer design rules

Load these into **KiCad → Board Setup → Design Rules → Constraints / Net Classes**
so DRC matches what JLCPCB can actually build (their standard 2-layer process):

| Rule | Value |
|------|-------|
| Min track width | 0.15 mm (use 0.25 mm for signals, 0.5 mm+ for power) |
| Min clearance | 0.15 mm (use 0.2 mm default) |
| Min via | 0.45 mm pad / 0.3 mm drill |
| Min annular ring | 0.13 mm |
| Min hole-to-hole | 0.5 mm |
| Silkscreen min width | 0.15 mm |
| Edge-to-copper | 0.3 mm |

Net classes:

| Class | Nets | Track width |
|-------|------|-------------|
| Power | +5V, +3V3, GND | 0.5–0.8 mm |
| USB | USB_DP, USB_DM | 0.25 mm, routed as a pair |
| Default | everything else | 0.25 mm |

---

## Placement plan (top view)

```
   ┌───────────────────────────────────────────────┐
   │ (M3)                                     (M3)  │
   │   ┌────────┐                                   │
   │   │ USB-C  │  U1   U2(LDO)   U3(CH340C)        │
   │   │  J1    │  ESD            Q1 Q2  SW1 SW2     │
   │   └────────┘                                   │
   │                                                │
   │   ████████████████████  ESP32-WROOM-32E (U4)   │
   │   █                  █                          │
   │   █   ANTENNA  KEEPOUT  (hangs off board edge)  │
   │   ████████████████████                          │
   │        ^ no copper/pour/parts under antenna     │
   │                                                │
   │   U5(BME280)   U6(IR recv)    Q3  J2(IR LED hdr)│
   │   (away from   (near edge,    D1 D2             │
   │    LDO/ESP32    facing out)                     │
   │ (M3)            heat)                     (M3)  │
   └───────────────────────────────────────────────┘
```

Placement priorities:
1. **USB-C at one edge**, U1 (ESD) right next to its data pins, then U3 (CH340C)
   — keep the USB path short and direct.
2. **ESP32 antenna at the opposite/short edge, overhanging the board outline**
   with a copper keepout (see below). Never place parts/pour/traces under it.
3. **BME280 away from the LDO and ESP32** (their heat skews temperature). Put it
   at a cooler corner; optionally add a slot/cutout around it and a few small
   thermal-relief slots to isolate it from board self-heating.
4. **IR receiver (U6) at a board edge facing outward** so the remote can reach it.
5. **Decoupling caps hard against** their IC power pins (C7/C8 at the WROOM 3V3
   pin, C5 at CH340C, C6 at BME280, C3/C4 at the LDO output).

---

## The three nets to get right

### 1. ESP32 antenna keepout (RF)
- The WROOM module's antenna end must **overhang the PCB edge**, or have a
  **full no-copper keepout** on *both* layers under and around the antenna
  (follow Espressif's "keepout zone" — no copper, no parts, no traces).
- Don't run any trace beneath the module's antenna section.

### 2. USB D+/D- differential pair
- Route `USB_DP`/`USB_DM` as a **pair**, same length, kept close, no stubs.
- Short and direct from J1 → U1 (ESD) → U3. At USB-2.0 Full-Speed (12 Mbps) this
  is forgiving; just keep them together, avoid vias, and don't route other signals
  between them. Ground pour underneath.

### 3. Auto-program transistors (Q1/Q2)
- Wire the **cross-couple exactly** as in `SCHEMATIC.md`
  (Q1: B=RTS,E=DTR,C=IO0 ; Q2: B=DTR,E=RTS,C=EN). A swap here = can't auto-flash.
- Keep `C_EN` (1 µF) close to the EN pin.

### Grounding
- **Pour GND on both layers**, stitch with vias (esp. around the WROOM thermal
  pad — multiple vias from the pad to the bottom GND pour) and along the USB path.

---

## KiCad → Gerbers (bare board)

1. **Plot** (`File → Plot`), output to `hardware/fab/gerbers/`:
   - Layers: `F.Cu, B.Cu, F.Paste, B.Paste, F.SilkS, B.SilkS, F.Mask, B.Mask,
     Edge.Cuts`.
   - Format **Gerber**, **4.6, mm**; check *Use extended X2*, *Include
     Netlist attributes*.
2. **Drill** (`Generate Drill Files`): Excellon, mm, PTH+NPTH, single file or
   per the JLCPCB note; **map** file optional.
3. **Zip** the gerbers folder → this is the upload for the bare PCB.
4. Sanity check by opening the zip in KiCad's **Gerber Viewer** (or JLCPCB's
   online viewer after upload).

> JLCPCB accepts KiCad-generated Gerbers directly; you do **not** need to switch
> to a "Protel/JLC" preset in modern KiCad 8.

## KiCad → BOM + CPL (for assembly)

Install the **"Fabrication Toolkit"** or **JLCPCB BOM/CPL** plugin (KiCad PCM),
then run it from Pcbnew — it outputs a JLCPCB-format **BOM** (with the `LCSC`
field from `BOM.csv`) and a **CPL/centroid** (placement) file.

Manual alternative:
- BOM: `Schematic → Tools → Export BOM`; ensure an `LCSC` column exists (copy the
  values from `BOM.csv`).
- CPL: `Pcbnew → File → Fabrication Outputs → Component Placement (.pos)`, mm,
  then rename columns to JLCPCB's `Designator,Mid X,Mid Y,Layer,Rotation`.

Add the `LCSC` part number as a **symbol field** on each component during
schematic capture so the BOM exports it automatically (values are in `BOM.csv`).

---

## Ordering at JLCPCB

1. Go to JLCPCB → **Add Gerber file** → upload the gerber zip. Review the preview.
2. Set: 2 layers, 1.6 mm, 1 oz, qty (order **1–2 first**), surface finish
   **HASL** (cheapest) or **ENIG** (nicer for fine-pitch — the WROOM/BME280 are
   fine but HASL is fine here).
3. Toggle **PCB Assembly** ON → Standard/Economic, **Assemble top side**, qty.
4. Upload **BOM** and **CPL** when prompted. Match each line to a JLCPCB part;
   confirm any **Extended** parts (the ESP32, CH340C, BME280, IR receiver) and
   that they're in stock.
5. Open the **placement review** — check rotations/polarity for U1–U6, Q1–Q3,
   D1/D2 (LED polarity and IC pin-1 are the usual gotchas; JLCPCB part rotation
   often differs from KiCad's — fix in the CPL or their editor).
6. Place order. The IR **emitter LED (IRLED1)** is off-board — solder it to a
   2-pin lead and plug into J2 yourself.

### Cost expectation
- Bare 2-layer PCB: a few dollars for 5.
- PCBA: dominated by the **Extended** parts' one-time setup (~$3 each ×4) + part
  cost. Expect roughly **$25–50 for a first small run** of assembled boards;
  per-board cost drops with quantity. Keeping everything else on **Basic** parts
  (as the BOM does) minimises the setup fees.

---

## Pre-order checklist

- [ ] DRC passes with the JLCPCB rules above (0 errors).
- [ ] ERC passes in the schematic (no unconnected pins, power flags placed on
      +5V/+3V3/GND).
- [ ] Antenna keepout clear on both layers; module overhangs edge.
- [ ] USB pair routed together, ESD part in-line.
- [ ] Auto-program cross-couple matches `SCHEMATIC.md`.
- [ ] Every BOM line confirmed **in stock** in JLCPCB's library (numbers drift!).
- [ ] LED + IC rotations/polarity verified in the placement preview.
- [ ] Ordered **one** board first to validate before a batch.
