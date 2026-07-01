# Enclosure — ESP32 Smart AC Controller

3D-printable two-part case for the `fab-sht40` board (65.2 × 39.3 mm). Friction
(drop-over) fit, **no supports**, tuned for a **Bambu Lab A1 mini**.

| File | What |
|------|------|
| `base.stl` | bottom tray (PCB sits here) — **70 × 46.7 × 12.6 mm** |
| `lid.stl`  | top cap with the IR window — outer **74 × 50.7 mm**, 8 mm tall |
| `generate_enclosure.py` | parametric source (edit + re-run to tweak) |
| `verify_plan.py` / `enclosure_plan.png` | proves openings line up with parts |
| `render3d.py` / `enclosure_3d.png` | exploded preview |

Assembled outer size ≈ **74 × 50.7 × 14.6 mm** (88 mm across the mounting ears).

## The IR rule (why the right end is wide open)
The IR **emitter D3** and **receiver U6** are on the right end and fire straight
**up** out of the PCB. ~940 nm IR is heavily attenuated by PLA/PETG, so there is
**no plastic over them** — the lid has one large open aperture (52–66 mm × 12–38 mm)
spanning both. The taller receiver module may even poke through it. Nothing in the
optical path = full range preserved.

**Aim the lid (top face) at the AC.** IR is line-of-sight out the top, so mount the
box on a wall / shelf with the lid pointing toward the indoor unit (receivers have
a wide ±45° field; the emitter cone is narrower, so keep it roughly facing the AC).

### Optional IR-filter window
The aperture is open by default. The lid top also has a **flush recess (17 × 29 mm,
1.2 mm deep)** around it, so if you want a sealed/finished look you can drop in a
**stick-on IR-pass window ≤ 16.5 × 28.5 mm, ≤ 1 mm thick** (smoked-IR acrylic) and
glue it. Use a real IR-transmitting filter — *not* generic tinted plastic, which
attenuates 940 nm and will cut range. Leaving it open always gives the best range.

## Other openings (all auto-aligned to the real CPL coordinates)
- **USB-C** — notch in the left wall at J1; the lid skirt is notched so it never
  covers the port.
- **SHT40 (U5)** temp/RH — vents in the lid (2 slots beside the IR window), the
  right wall, and the bottom wall, so it reads ambient air, not the box's own heat.
- **EN / BOOT** — Ø3.8 holes in the lid; press with a paperclip to flash.
- **Power / status LEDs** (D1, D2) — Ø2.6 view holes.
- **ESP32 antenna** — 3 mm extra clearance on the top wall, no metal, no vents there.

## Wall mounting
The base has two **flat ears at floor level** (left + right walls) with **Ø4.4 holes**
(M4 / #8 screws), 88 mm hole-to-hole. Screw the base flat to a wall with the floor
against the wall — the lid (IR face) then points straight out into the room. The ears
sit below the USB-C port height, so the cable still clears them. (Set `MOUNT_EARS =
False` in the script for a plain bench-top box.)

## Printing (A1 mini)
- **Material:** PLA or PETG. (Near a hot AC vent or in sun, prefer **PETG/ASA** —
  PLA softens ~55 °C.)
- **Layer height:** 0.20 mm · **Walls:** 3 · **Top/bottom:** 4 layers · **Infill:** 15 %.
- **Supports:** none.
- **Orientation:**
  - `base.stl` — **as exported** (floor on the plate, opening up).
  - `lid.stl` — **flip it top-face-down** (flat top on the plate). Skirt and the
    PCB hold-down bosses then print upward as clean vertical features; the IR
    window / holes / vents come out crisp against the bed. The IR-filter recess
    becomes a shallow 1.5 mm cantilever — prints clean, no support.
- Print time ≈ 1–1.5 h each, ~15 g PLA per part.

## Assembly
1. Drop the PCB into the base — it rests on the internal shelf (component side up).
2. Press the lid on; its four internal bosses clamp the board onto the shelf and
   the skirt grips the base (0.2 mm friction fit). Add a dab of glue or a strip of
   tape if you want it permanent.

## Tweaking
Everything is parametric in `generate_enclosure.py` (wall thickness, clearances,
head height, vent counts, IR-window rectangle). After editing:

```bash
python3 generate_enclosure.py   # -> base.stl, lid.stl
python3 verify_plan.py          # -> enclosure_plan.png (check alignment)
```

Requires `trimesh` + `manifold3d` (`pip install --user trimesh manifold3d`).
Both parts are validated **watertight + manifold** on generation.
