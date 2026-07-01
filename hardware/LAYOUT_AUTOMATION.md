# Automating PCB Layout — Tool Research & Pipeline

Research into **free / open-source** tooling to turn the naively grid-placed
`ac_controller.kicad_pcb` into a sensibly **placed and routed** board with
**minimal/no GUI** interaction (KiCad 10.0.4; `kicad-cli` + `pcbnew` Python
reachable headlessly). Findings below are web-researched **and** empirically
verified on this machine where noted.

## Bottom line

- **Routing is a solved free/headless problem** → **Freerouting** (v2.2.4, 2025)
  via a Specctra DSN→SES round-trip.
- **Placement is the real gap** → there is **no good free, connectivity-driven,
  headless auto-placer**. The pragmatic answer is a **scripted heuristic placer**
  (written against the `pcbnew` Python API) that clusters by subsystem, then hand
  off to Freerouting.
- The KiCad↔Freerouting bridge **must** go through the `pcbnew` Python API
  (not `kicad-cli`). **Verified working headless on this install.**

## What I verified on THIS machine (KiCad 10.0.4)

| Check | Result |
|-------|--------|
| `kicad-cli pcb export` has a `dsn`/`ses` subcommand | ❌ **No** (only gerbers/drill/step/…); confirms round-trip can't use `kicad-cli` |
| `pcbnew.ExportSpecctraDSN(filename)` (1-arg) headless | ❌ returns **False** (needs a GUI "current board") |
| `pcbnew.ExportSpecctraDSN(board, filename)` (2-arg) headless | ✅ **works** — produced a valid 33 KB `.dsn` from our board |
| `pcbnew.ImportSpecctraSES(board, filename)` (2-arg) headless | ✅ signature accepted headless (round-trips a real `.ses`) |
| `pcbnew` placement/connectivity API | ✅ `GetFootprints()`, `GetFullRatsnest()`, `GetConnectivity()`, per-FP `GetCourtyard()/GetBoundingBox()/SetPosition()/SetOrientation()` |
| Java (for Freerouting) | ❌ **not installed** — needs a free JRE (e.g. Temurin/OpenJDK 17+) |

> The 2-arg `ExportSpecctraDSN`/`ImportSpecctraSES` forms are undocumented (the
> docstring only shows the 1-arg form) but are the key to headless operation. The
> 1-arg form silently fails outside the GUI.

## Routing — Freerouting (free, headless)

- Actively maintained Java autorouter; **latest v2.2.4 (May 2025)**. Imports
  Specctra `.dsn`, exports routed `.ses`. [repo](https://github.com/freerouting/freerouting)
- Headless: `--gui.enabled=false`. Round-trip CLI:
  ```bash
  java -jar freerouting-2.2.4.jar --gui.enabled=false \
       -de board.dsn -do board.ses -mp 100
  ```
  `-de` input design, `-do` output session, `-mp` = max optimizer passes.
  ([CLI docs](https://github.com/freerouting/freerouting/blob/master/docs/command_line_arguments.md))
- **Pin to ≥ v2.2.0**: before it, `-mp` was *ignored in headless mode*
  (issue [#522](https://github.com/freerouting/freerouting/issues/522)).
- **Don't trust Freerouting's internal DRC** — it's clearance-only. Gate on
  KiCad's engine: `kicad-cli pcb drc --format json` after import
  (issue [#574](https://github.com/freerouting/freerouting/issues/574)).
- **Freerouting does NOT fill copper zones** — re-fill ground pours in KiCad
  after SES import.

## Placement — the gap (free options evaluated)

| Tool | Verdict |
|------|---------|
| [FD-Autoplacer](https://github.com/JarrettR/FD-Autoplacer) | Experimental force-directed placer; **can't write positions back to `.kicad_pcb`** (author calls it a finished experiment). Not usable as-is. |
| [kicad-parts-placer](https://github.com/snhobbs/kicad-parts-placer) | Headless CLI, but **exact CSV coordinate placement** — not intelligent/connectivity-driven. Useful as a "apply my computed positions" backend. |
| KiCad built-in **Auto-Place Footprints** | Minimizes ratsnest, tries 0/90/180 orientations, but **GUI-only and rudimentary** (docs: "no software can guess what the user wants"). |
| [kigadgets](https://github.com/atait/kicad-python) | Ergonomic headless `pcbnew` wrapper; only **tested through KiCad 9**, optional convenience layer. |

→ **Conclusion:** write a small **heuristic placer** with `pcbnew` Python:
connectors + ESP32 antenna to the board edge, decoupling caps hard against their
IC power pins, group each subsystem (power / USB-UART / MCU / sensor+IR), and use
`GetFullRatsnest()` length as a cheap quality metric (optionally a few rounds of
force-directed nudging on the ratsnest).

## Results — actually run on this board (not theory)

I built and ran the full pipeline end-to-end. Artifacts are in `kicad/`:

| Stage | Tool | Outcome |
|-------|------|---------|
| Placement | `build_board.py` (anchors + connectivity-centroid clustering, caps bound to their IC, courtyard collision, **U4 inverted-T keep-out + 2 mm fan-out halo**, **antenna + perimeter routing keep-outs**, silk hidden) | `placed.kicad_pcb` — **subsystem-clustered, 68×42 mm**, 35 fps, 56 nets. See `placed_top.png`. |
| DSN export | `pcbnew.ExportSpecctraDSN(board, …)` | ✅ headless; **carries the keep-outs** so Freerouting respects them |
| Routing | Freerouting 2.2.4, `-mp 40` | **100% routed (0 unconnected) in ~6 s**. See `routed_top.png`. |
| Import | `pcbnew.ImportSpecctraSES(board, …)` | ✅ |
| Finish | `finish_board.py` | GND pour both layers (solid), zones filled → `finished.kicad_pcb`, `finished_top.png`, `finished_3d.png` |
| DRC | `kicad-cli pcb drc` | **ZERO violations, 0 unconnected, 0 schematic-parity** — fully clean (silk included). |
| Fab | `kicad-cli pcb export gerbers/drill/pos` | `ac_controller_gerbers.zip` + `ac_controller_cpl.csv` — uploadable to JLCPCB |

### Size optimization (review by 3 parallel agents → implemented)

Started at **84×60 mm (5040 mm²)**, optimized to **68×42 mm (2856 mm²) — a 43%
area reduction** with the board still **100% routed and fully DRC-clean**. The
key fixes (all in `build_board.py`):
- **The ESP32 courtyard is an inverted-T** (a full-width antenna keep-out bar over
  a narrow body), not a U. Collision now uses the body **pad bbox** + the
  full-width antenna bar, with a **2 mm fan-out halo** so the 14-per-side WROOM
  pads can escape (no track fits between them).
- **Antenna overhangs the top edge** — the huge keep-out bar leaves the board
  instead of eating ~1000 mm² of area.
- **Keep-outs created before routing** (antenna + a 0.5 mm perimeter ring) so the
  DSN carries them and Freerouting avoids the antenna and the board edge.
- **Net classes / margins** tuned to the routability floor (Agent 3 found ~60×42
  is the WROOM minimum; 68×42 leaves comfortable routing headroom).
- Skipped (per the agents, <6% gain each): 2-sided assembly, 0402 passives.

**Assessment.** With proper placement and **all pads netted** (the ESP32 thermal
pad has several pads sharing number "39" — netting only one of them was what
caused phantom shorts *and* blocked the router), the free headless pipeline
produces a **fully-routed, electrically-DRC-clean 2-layer board**. The two early
problems (shorts, partial routing) were that one bug, not a Freerouting
limitation.

**Automated & clean:** ✅ GND pour both layers (solid). ✅ Antenna keep-out, now
**overhanging the board edge**, respected by the router. ✅ Silk hidden → zero silk
DRC. ✅ Perimeter keep-out → no copper-to-edge violations. Final DRC: **0 of
everything.**

**Still worth a human eye before you spend money** (judgment a script shouldn't fake):
- **USB-C D+/D-** — routed as ordinary nets (fine for USB-2 Full-Speed at 12 Mbps,
  but not impedance-matched); review if you care.
- **Silk is hidden** — if you want reference designators on the board for hand-
  assembly/debug, re-enable them in KiCad and nudge the overlapping ones.
- **Re-verify LCSC stock** and always order **one** board first before a batch.

## Recommended pipeline (free, mostly headless)

```
 grid-placed .kicad_pcb
   │  ① heuristic placer            pcbnew Python  (script — to write)
   ▼
 placed .kicad_pcb
   │  ② ExportSpecctraDSN(board, "b.dsn")   pcbnew Python   ✅ verified
   ▼
 b.dsn
   │  ③ freerouting --gui.enabled=false -de b.dsn -do b.ses -mp 100   (needs JRE)
   ▼
 b.ses
   │  ④ ImportSpecctraSES(board, "b.ses") + refill zones + SaveBoard  pcbnew  ✅ sig verified
   ▼
 routed .kicad_pcb
   │  ⑤ kicad-cli pcb drc --format json     (gate — KiCad's real DRC)
   ▼
 verified board  →  gerbers/3D as before
```

**Still needs the GUI / hand-work (don't automate):**
- **ESP32 antenna keepout** — place the module overhanging the edge with a copper
  keepout; lock it before routing.
- **USB-C differential pair** — set up the pair and hand-route (or lock) D+/D-;
  autorouters handle diff pairs poorly.
- Final visual sanity pass.

**Known pitfalls:** Freerouting may leave DRC violations (→ ⑤ gates it); it
ignores copper pours (→ re-fill zones in ④); net classes / layer count / board
outline must be correct in the `.kicad_pcb` *before* DSN export.

## One dependency to add

Freerouting is Java and **no JRE is installed**. Install a free one (Adoptium
Temurin / OpenJDK 17+), or skip routing automation and only auto-place + hand-route.

## Sources
Freerouting [repo](https://github.com/freerouting/freerouting) ·
[releases](https://github.com/freerouting/freerouting/releases) ·
[CLI docs](https://github.com/freerouting/freerouting/blob/master/docs/command_line_arguments.md) ·
[#522](https://github.com/freerouting/freerouting/issues/522) ·
[#574](https://github.com/freerouting/freerouting/issues/574) ·
KiCad [CLI docs](https://docs.kicad.org/master/en/cli/cli.html) ·
[SPECCTRA_DB](https://docs.kicad.org/doxygen/classDSN_1_1SPECCTRA__DB.html) ·
[feature #14339](https://gitlab.com/kicad/code/kicad/-/work_items/14339) ·
[pcbnew scripting](https://github.com/KiCad/kicad-doc/blob/master/src/pcbnew/pcbnew_python_scripting.adoc)
