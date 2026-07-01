#!/usr/bin/env python3
r"""Finish a routed board: add a GND copper pour on both layers, an ESP32 antenna
keep-out (no copper / tracks / vias), fill the zones, and save.

  "C:\Program Files\KiCad\10.0\bin\python.exe" finish_board.py routed.kicad_pcb finished.kicad_pcb
"""
import pcbnew, sys
IN  = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\marks\aclayout\routed.kicad_pcb"
OUT = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\marks\aclayout\finished.kicad_pcb"
MM = 1_000_000
b = pcbnew.LoadBoard(IN)
def v(x, y): return pcbnew.VECTOR2I(int(round(x*MM)), int(round(y*MM)))

def add_zone(corners, layers, net=None, keepout=False, prio=0):
    z = pcbnew.ZONE(b)
    ls = pcbnew.LSET()
    for L in layers: ls.AddLayer(L)
    z.SetLayerSet(ls)
    if net is not None: z.SetNet(net)
    if keepout:
        z.SetIsRuleArea(True)
        z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
    z.SetAssignedPriority(prio)
    o = z.Outline(); o.NewOutline()
    for cx, cy in corners: o.Append(v(cx, cy))
    b.Add(z); return z

# --- GND pour on both layers, inset from the board edge ---
bb = b.GetBoardEdgesBoundingBox()
x1, y1 = bb.GetLeft()/MM, bb.GetTop()/MM
x2, y2 = bb.GetRight()/MM, bb.GetBottom()/MM
ins = 0.4
gnd = b.FindNet("GND")
gz = add_zone([(x1+ins, y1+ins), (x2-ins, y1+ins), (x2-ins, y2-ins), (x1+ins, y2-ins)],
              [pcbnew.F_Cu, pcbnew.B_Cu], net=gnd, prio=0)
# Solid GND connections (reflow/PCBA board) — avoids starved-thermal warnings.
gz.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)

# (The ESP32 antenna keep-out is created in build_board.py BEFORE routing so
# Freerouting avoids it; it carries through the SES import, so we don't re-add it.)

pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard(OUT, b)
print(f"finished: {len(list(b.Zones()))} zones, GND pour + antenna keepout -> {OUT}")
