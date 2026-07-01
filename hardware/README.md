# Hardware — Integrated PCB (orderable)

This folder is the **manufacturable, integrated board**: a bare
**ESP32-WROOM-32E** with USB-C, USB-UART programming, an on-board 3.3 V
regulator, on-board BME280, an on-board **SMD IR receiver** (to learn your
remote) and an on-board **SMD IR emitter LED** (to send commands to the AC).
**Fully JLCPCB-PCBA assembled** — every part is SMD; the only through-hole pads
are the ESP32 thermal vias (reflowed) and the USB-C connector's anchor legs
(which JLC assembles). Nothing is left for you to hand-solder.

> Trade-off vs. the earlier external-LED design: the IR emitter is now an
> **on-board top-view LED**, so the **board itself must face the AC** (no aimable
> flying lead). That's the cost of full machine assembly.

> The breadboard/prototype wiring in [`../docs/HARDWARE.md`](../docs/HARDWARE.md)
> is the *quick bring-up* version using dev-board + modules. **This** folder is
> the integrated PCB you actually order. The firmware pin map is identical, so
> firmware needs no changes between the two.

## Files

| File | What it is |
|------|------------|
| [`kicad/ac_controller.kicad_pro`](kicad/ac_controller.kicad_pro) | KiCad project (open this) |
| [`kicad/ac_controller.kicad_sch`](kicad/ac_controller.kicad_sch) | **Real, openable KiCad 10 schematic.** ERC-validated: **0 errors** |
| [`kicad/ac_controller.pdf`](kicad/ac_controller.pdf) | Rendered schematic to eyeball without opening KiCad |
| [`kicad/ac_controller.net`](kicad/ac_controller.net) | Exported netlist (connectivity reference) |
| [`kicad/ac_controller.kicad_pcb`](kicad/ac_controller.kicad_pcb) | Board with **all footprints placed** (un-routed starting point; also the source of the 3D render) |
| [`kicad/board3d.png`](kicad/board3d.png) | **3D render** of the populated board |
| [`kicad/gen_schematic.py`](kicad/gen_schematic.py) | Generator for the schematic (reads your KiCad symbol libs) |
| [`kicad/gen_pcb.py`](kicad/gen_pcb.py) | Generator for the placed PCB / 3D render (uses the `pcbnew` Python API) |
| [`SCHEMATIC.md`](SCHEMATIC.md) | Human-readable schematic: every sub-circuit + net-by-net netlist |
| [`BOM.csv`](BOM.csv) | PCBA bill of materials with LCSC part numbers (Basic/Extended flagged) |
| [`LAYOUT.md`](LAYOUT.md) | Stackup, JLCPCB design rules, placement, routing, **Gerber export + ordering steps** |
| [`LAYOUT_AUTOMATION.md`](LAYOUT_AUTOMATION.md) | **Researched + tested** free/headless place-&-route pipeline (pcbnew placer + Freerouting) |
| [`kicad/build_board.py`](kicad/build_board.py) | Heuristic placer: nets the board + clusters parts by subsystem |
| [`kicad/run_pipeline.sh`](kicad/run_pipeline.sh) | One-shot place → DSN → Freerouting → SES → DRC |
| [`kicad/placed.kicad_pcb`](kicad/placed.kicad_pcb) · `placed_top.png` | Subsystem-placed board, **68×42 mm** — fixes the grid layout |
| [`kicad/routed.kicad_pcb`](kicad/routed.kicad_pcb) · `routed_top.png` | **Fully autorouted** (0 unconnected) |
| [`kicad/finished.kicad_pcb`](kicad/finished.kicad_pcb) · `finished_top.png` · `finished_3d.png` | **Finished board**: GND pour + antenna keep-out. **68×42 mm, DRC fully clean (0 of everything)**. |
| [`kicad/finish_board.py`](kicad/finish_board.py) | Adds the GND pour and fills zones |
| [`kicad/ac_controller_gerbers.zip`](kicad/ac_controller_gerbers.zip) | **Gerbers + drill** from the finished board — uploadable to JLCPCB |
| [`kicad/ac_controller_cpl.csv`](kicad/ac_controller_cpl.csv) | **CPL / centroid** placement file for PCBA (pairs with `BOM.csv`) |

### 3D model

`kicad/board3d.png` is a real 3D render (every part uses its KiCad-library 3D
model). The `.kicad_pcb` it came from just has the footprints auto-placed on a
grid — it is **not routed and not sensibly placed yet**. For the *real* board +
its proper 3D view: open the project, **Tools → Update PCB from Schematic** (this
pulls the nets/ratsnest), lay it out per `LAYOUT.md`, then **View → 3D Viewer**
(or re-run `gen_pcb.py` to re-render). Regenerate the render headlessly with:
`kicad-cli pcb render --perspective --quality high -o board3d.png ac_controller.kicad_pcb`.

## Status: schematic is done & verified; layout is the remaining step

The schematic was generated as code and **validated with `kicad-cli` (KiCad
10.0.4): ERC reports 0 errors.** The exported netlist was checked node-by-node —
59 nets, no shorts, the auto-reset cross-couple and I²C address strap are correct.
So you do **not** have to capture the schematic by hand.

What's *intentionally* left for you (it needs the KiCad GUI and can't be done
headlessly): **PCB placement, routing, DRC, and Gerber export.** That's where a
board can go wrong, so it belongs where you can see and check it.

### Workflow to an order

1. **Open** `kicad/ac_controller.kicad_pro` in KiCad. Open the schematic.
   - It uses a compact "net-label" style (each pin carries a global label instead
     of drawn wires) so it's electrically complete but visually spread out —
     rearrange to taste, or just proceed; connectivity is already correct.
   - Run **Tools → Update Symbols from Library** once to clear the 6 cosmetic
     `lib_symbol_mismatch` warnings (artifacts of code-generation).
2. **Create the PCB** (Tools → Update PCB from Schematic). Footprints are already
   assigned (verified against your libraries).
3. **Lay out + route** following [`LAYOUT.md`](LAYOUT.md) — 2-layer; mind the
   antenna keepout, USB pair, and auto-reset transistors.
4. **Run DRC** with the JLCPCB rules in `LAYOUT.md`. Fix violations.
5. **Export** Gerbers + drill, and BOM + CPL (assembly) per `LAYOUT.md`.
6. **Order** at JLCPCB: upload Gerber zip, enable PCB Assembly, upload BOM + CPL,
   review the placement preview, pay.

To re-generate the schematic after editing the design, run
`python3 kicad/gen_schematic.py` (it reads symbols from your KiCad install; set
`KICAD_SYMBOL_DIR` if it's not at the default path), then re-run
`kicad-cli sch erc`.

## Why not ready-made Gerbers?

Gerbers are the *output of a routed board*. The schematic is generated and
machine-verified, but routing + DRC must happen in your KiCad GUI where copper
can actually be checked — shipping blind Gerbers would risk paying for a dead
board (unrouted net, bad USB pair). One spin of layout and you're there.

## ⚠️ Before you order — verify these

- **LCSC part numbers drift / go out of stock.** Re-check every line in `BOM.csv`
  against the live JLCPCB Parts Library at order time; swap any out-of-stock part
  for an equivalent and update the footprint if the package changes. The IR LED
  (D3) is a suggested 1206 940 nm part — pick any in-stock equivalent.
- The **IR receiver (U6) pinout is confirmed** from the IRM-H6XXT datasheet
  (pad 1=GND, 2=GND, 3=OUT, 4=Vcc) and wired correctly.
- **Prefer JLCPCB "Basic" parts** (no per-part loading fee). Extended parts cost
  ~$3 setup each — the BOM flags which is which so you can minimise that.
- Order **one** board first, validate (especially the IR learn function), then
  order a batch.
