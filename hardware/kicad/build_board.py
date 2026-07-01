#!/usr/bin/env python3
r"""
Build a ROUTABLE, sensibly-PLACED .kicad_pcb from the netlist, headlessly.

  - loads each footprint and wires its pads to nets parsed from ac_controller.net
  - places anchor parts (ICs, connectors) on a curated floorplan
  - clusters every remaining passive near the parts it connects to (centroid of
    its net neighbours) with bounding-box collision avoidance
  - draws a board outline and sets 2-layer track/clearance defaults

Run with KiCad's python (Windows):
  "C:\Program Files\KiCad\10.0\bin\python.exe" build_board.py <netlist> <out.kicad_pcb>
"""
import pcbnew, re, os, sys, math

NET = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\marks\aclayout\ac_controller.net"
OUT = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\marks\aclayout\placed.kicad_pcb"
FPDIR = r"C:\Program Files\KiCad\10.0\share\kicad\footprints"
MM = 1_000_000
def vec(x, y): return pcbnew.VECTOR2I(int(round(x*MM)), int(round(y*MM)))

# ---------- parse netlist ----------
src = open(NET, encoding="utf-8").read()
def blocks(text, pattern):
    """Balanced-paren blocks whose opening matches `pattern` (a regex)."""
    out = []
    for m in re.finditer(pattern, text):
        k = m.start(); d = 0; j = k
        while j < len(text):
            if text[j] == '(': d += 1
            elif text[j] == ')':
                d -= 1
                if d == 0: break
            j += 1
        out.append(text[k:j+1])
    return out

comps = []
for b in blocks(src, r'\(comp\s+\(ref'):
    ref = re.search(r'\(ref "([^"]+)"\)', b)
    fp  = re.search(r'\(footprint "([^"]+)"\)', b)
    if ref and fp: comps.append((ref.group(1), fp.group(1)))

nets = {}
nsec = src[src.find("(nets"):]
for b in blocks(nsec, r'\(net\s+\(code'):
    name = re.search(r'\(name "([^"]+)"\)', b)
    if not name: continue
    nodes = re.findall(r'\(node\s*\(ref "([^"]+)"\)\s*\(pin "([^"]+)"', b)
    if nodes: nets[name.group(1)] = nodes

# ---------- build board + footprints + nets ----------
board = pcbnew.BOARD()
ds = board.GetDesignSettings()
# Net-class rules MUST be set before the DSN export so Freerouting routes with
# JLCPCB-compatible widths/vias — otherwise it picks tiny vias that KiCad DRC
# then flags as drill_out_of_range / shorts.
try:
    nc = ds.m_NetSettings.GetDefaultNetclass()   # KiCad-10 path (no ds.GetDefault)
    nc.SetClearance(int(0.2*MM)); nc.SetTrackWidth(int(0.25*MM))
    nc.SetViaDiameter(int(0.6*MM)); nc.SetViaDrill(int(0.3*MM))  # 0.15mm annular - Freerouting-safe
except Exception as e:
    print("netclass set warn:", e)
try:
    ds.m_MinThroughDrill = int(0.2*MM)   # ESP32 thermal-via 0.2mm holes are JLC-valid
except Exception as e:
    print("min-hole warn:", e)

fp_by_ref = {}
for ref, fpid in comps:
    lib, name = fpid.split(":")
    fp = pcbnew.FootprintLoad(os.path.join(FPDIR, lib + ".pretty"), name)
    if fp is None:
        print("MISS", fpid); continue
    fp.SetReference(ref); board.Add(fp); fp_by_ref[ref] = fp

net_obj = {}
def get_net(n):
    if n not in net_obj:
        ni = pcbnew.NETINFO_ITEM(board, n); board.Add(ni); net_obj[n] = ni
    return net_obj[n]
# A pad NUMBER can repeat within a footprint (e.g. the ESP32 thermal pad 39 + its
# stitching vias all share "39"). FindPadByNumber returns only one, leaving the
# rest <no net> and shorting. So iterate EVERY pad and net it by its number.
pad_net = {}
for nname, nodes in nets.items():
    get_net(nname)
    for ref, pin in nodes:
        pad_net[(ref, pin)] = nname
for ref, fp in fp_by_ref.items():
    for pad in fp.Pads():
        nn = pad_net.get((ref, pad.GetNumber()))
        if nn: pad.SetNet(net_obj[nn])

# neighbours: ref -> set of refs sharing a SIGNAL net (ignore GND/power rails so
# parts cluster to their function, not to everything).
RAILS = {"GND", "+3V3", "+5V"}
neigh = {r: set() for r in fp_by_ref}
for nname, nodes in nets.items():
    if nname in RAILS: continue
    refs = [r for r, _ in nodes if r in fp_by_ref]
    for a in refs:
        for c in refs:
            if a != c: neigh[a].add(c)
# Decoupling caps connect only to rails -> no signal neighbour -> they'd scatter.
# Bind each to the IC it decouples so it clusters tight against that part.
CAP_PARENT = {"C1":"U2","C3":"U2","C4":"U2","C5":"U3","C6":"U5",
              "C7":"U4","C8":"U4","C_EN":"U4","C_irrx":"U6"}
for cap, ic in CAP_PARENT.items():
    if cap in neigh and ic in fp_by_ref:
        neigh[cap].add(ic); neigh.setdefault(ic, set()).add(cap)

# ---------- placement ----------
# Curated anchors for the big/edge parts (mm, rotation deg). Antenna of U4 faces
# the top edge; connectors at edges; BME280 in a cooler corner.
# Compact floorplan. U4 (ESP32) sits centre-right with its antenna toward the top
# edge (it overhangs — best for RF + smaller board). The IR receiver/header live
# in the RIGHT ARM beside the module body; everything else packs to the left.
ANCHOR = {
    "U4": (40, 16, 0),    # ESP32 FIRST. Moved UP (was y24) so the PCB antenna sits at /
                          #   overhangs the top edge instead of being buried ~7mm inside (P1)
    "J1": (5, 20, 90),    # USB-C, left edge — rot 90 = mouth faces -X (the edge). The
                          #   real bug was the board extending PAST the mouth (buried it);
                          #   the left edge is now cut flush to the mouth (see outline below).
    "U1": (12, 20, 0),    # ESD, next to USB
    "U2": (9, 33, 0),     # LDO, lower-left
    "U3": (21, 18, 0),    # CH340C
    "U5": (55, 38, 0),    # SHT40 temp/humidity -> bottom-right, away from ESP32 + LDO heat (P3);
                          #   pulled in from the extreme corner for routing access to the DFN
    "U6": (55, 21, 90),   # IR receiver, right arm beside U4 body
    "D3": (58, 33, 0),    # on-board SMD IR emitter LED (board faces the AC)
    "SW1": (27, 9, 0),    # EN button (top)
    "SW2": (33, 9, 0),    # BOOT button (top)
    "D1": (6, 9, 0),      # power LED, top-left
    # ESP32 3V3 decoupling RIGHT at U4 pin-2 (3V3, top-left of the module) instead
    # of clustering to the module centroid ~21mm away (P2). Left of the body so the
    # 2mm fan-out halo doesn't reject them.
    "C8": (28, 14, 0),    # 0.1uF decouple in the slot beside U4 pin-2 (3V3, ~y12)
    "C7": (28, 16.5, 0),  # 10uF bulk just below it
}
placed = {}
def edges(fp, x=None, y=None):
    if x is not None: fp.SetPosition(vec(x, y))
    try:
        bb = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
        if bb.GetWidth() > 0 and bb.GetHeight() > 0:
            return bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()
    except Exception: pass
    bb = fp.GetBoundingBox()
    return bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()
def pad_extent(fp):
    """Union bbox of a footprint's PADS (real copper) — excludes the silk/antenna
    keep-out that inflates the ESP32 courtyard."""
    L = T = 10**13; R = B = -10**13
    for p in fp.Pads():
        bb = p.GetBoundingBox()
        L = min(L, bb.GetLeft()); T = min(T, bb.GetTop())
        R = max(R, bb.GetRight()); B = max(B, bb.GetBottom())
    if R < L:                       # no pads -> fall back to bbox
        return edges(fp)
    return L, T, R, B
_u4 = []
def u4_blocks():
    """U4's keep-out as TWO rects (body pads + antenna strip) instead of the
    phantom U-shaped courtyard bbox, so parts can sit in the side arms."""
    if _u4 or "U4" not in placed: return _u4
    fp = fp_by_ref["U4"]
    pl, pt, pr, pb = pad_extent(fp)                 # narrow module body (where pads are)
    cl, ct, cr, cb = edges(fp)                      # full courtyard (incl. antenna bar)
    _u4.append((pl, pt, pr, pb))                    # body stem
    # The WROOM courtyard is an inverted-T: a FULL-WIDTH antenna keep-out bar above
    # the body. Block the whole bar (it overhangs the top edge, so it's off-board).
    if ct < pt: _u4.append((cl, ct, cr, pt))
    return _u4
def collides(fp, x, y, pad=0.45, u4pad=2.0):
    # Reserve a 2mm fan-out halo around the ESP32 body so its 14-per-side pads can
    # escape (no track fits *between* WROOM pads). Pack tight (0.45mm) elsewhere.
    l1, t1, r1, b1 = edges(fp, x, y)
    for r2 in placed:
        if r2 == "U4":
            boxes, p = u4_blocks(), int(u4pad*MM)
        else:
            boxes, p = [edges(fp_by_ref[r2])], int(pad*MM)
        for l2, t2, r2e, b2 in boxes:
            if l1 < r2e + p and r1 + p > l2 and t1 < b2 + p and b1 + p > t2:
                return True
    return False
def place(ref, x, y, rot):
    fp = fp_by_ref[ref]; fp.SetOrientationDegrees(rot)
    for r in range(0, 130):                         # fine spiral, tight packing
        for a in range(0, 360, 20):
            cx = x + r*0.5*math.cos(math.radians(a))
            cy = y + r*0.5*math.sin(math.radians(a))
            if 1 < cx < 62 and 1 < cy < 48 and not collides(fp, cx, cy):
                fp.SetPosition(vec(cx, cy)); placed[ref] = (cx, cy); return
    fp.SetPosition(vec(x, y)); placed[ref] = (x, y)

for ref, (x, y, rot) in ANCHOR.items():
    if ref in fp_by_ref: place(ref, x, y, rot)

# everything else: target = centroid of placed net-neighbours (else board centre)
rest = [r for r in fp_by_ref if r not in placed]
for _ in range(3):  # a few passes so parts can cluster to each other too
    for ref in list(rest):
        ns = [placed[c] for c in neigh[ref] if c in placed]
        if not ns: continue
        tx = sum(p[0] for p in ns)/len(ns); ty = sum(p[1] for p in ns)/len(ns)
        place(ref, tx, ty, 0);
        if ref in rest: rest.remove(ref)
for ref in rest:           # leftovers with no placed neighbour
    place(ref, 30, 24, 0)

# Hide all silkscreen ref/value text — guarantees zero silk DRC on a dense board.
# (Assembly uses the CPL + BOM, not silk labels.)
for fp in fp_by_ref.values():
    fp.Reference().SetVisible(False)
    fp.Value().SetVisible(False)

# D3 cathode polarity triangle on silkscreen (JLCPCB DFM request). The Everlight
# SMD3528 footprint has no clear polarity mark, so JLC's engineers had to hand-check
# D3 every order. Draw a small filled triangle on F.SilkS pointing AT the cathode pad
# (pad "1" = net IR_LED_K, the smaller pad) so the cathode is unambiguous at DFM.
# Read the pad's REAL board position + the part rotation so the marker stays correct
# no matter where/how placement moved D3.
d3 = fp_by_ref.get("D3")
if d3:
    kpad = next((p for p in d3.Pads() if p.GetNumber() == "1"), None)
    if kpad:
        ang = math.radians(d3.GetOrientationDegrees())
        ux, uy = -math.cos(ang), -math.sin(ang)   # unit vector toward cathode (local -X)
        px, py = -uy, ux                           # perpendicular (triangle base)
        kc = kpad.GetPosition(); kx, ky = kc.x/MM, kc.y/MM
        half = kpad.GetBoundingBox().GetWidth()/MM / 2
        tipd, based, hw = half + 0.25, half + 1.05, 0.5   # tip 0.25mm off the pad, 0.8mm tall
        tip  = (kx + ux*tipd,  ky + uy*tipd)              # vertex pointing at the cathode
        b1   = (kx + ux*based + px*hw, ky + uy*based + py*hw)
        b2   = (kx + ux*based - px*hw, ky + uy*based - py*hw)
        tri = pcbnew.PCB_SHAPE(board); tri.SetShape(pcbnew.SHAPE_T_POLY)
        sps = pcbnew.SHAPE_POLY_SET(); sps.NewOutline()
        for xx, yy in (tip, b1, b2):
            sps.Append(int(round(xx*MM)), int(round(yy*MM)))
        tri.SetPolyShape(sps)
        tri.SetLayer(pcbnew.F_SilkS); tri.SetFilled(True); tri.SetWidth(int(0.12*MM))
        board.Add(tri)
    else:
        print("D3 cathode pad '1' not found - polarity triangle skipped")

# ---------- board outline ----------
# Size from PAD extents + 1.5mm so the big ESP32 antenna keep-out bar OVERHANGS the
# top edge (off-board) instead of eating board area. The keep-out is re-created as
# a rule area over the on-board sliver in finish_board.py.
ee = [pad_extent(fp_by_ref[r]) for r in placed]
x1 = min(e[0] for e in ee)/MM - 2.5; y1 = min(e[1] for e in ee)/MM - 2.5
x2 = max(e[2] for e in ee)/MM + 2.5; y2 = max(e[3] for e in ee)/MM + 2.5
# USB-C is an EDGE receptacle: its mouth must sit AT the board edge so a cable can
# be inserted. The generic -2.5mm margin would bury the mouth under ~3mm of FR4, so
# cut the left edge flush to J1's front (mouth) pads; the metal shell overhangs
# off-board. J1 (rot 270) is the left-most part, so this also defines the left edge.
j1 = fp_by_ref.get("J1")
if j1:
    # Trim the left edge close to the USB-C mouth so a cable inserts (the original
    # 3.2mm FR4 lip in front of the connector blocked the plug), but leave ~1.5mm
    # of front margin: the USB2.0 receptacle's redundant pads (A6=B6 D+, A7=B7 D-)
    # are bridged by a trace routed IN FRONT of the 0.5mm-pitch pad row, which needs
    # board there with 0.5mm edge clearance.
    x1 = min(p.GetBoundingBox().GetLeft() for p in j1.Pads())/MM - 1.5
rect = pcbnew.PCB_SHAPE(board); rect.SetShape(pcbnew.SHAPE_T_RECT)
rect.SetStart(vec(x1, y1)); rect.SetEnd(vec(x2, y2))
rect.SetLayer(pcbnew.Edge_Cuts); rect.SetWidth(int(0.15*MM)); board.Add(rect)

# ---------- routing keep-outs BEFORE routing (carried into the DSN) ----------
def rule_area(corners, fills=True):
    z = pcbnew.ZONE(board); ls = pcbnew.LSET()
    ls.AddLayer(pcbnew.F_Cu); ls.AddLayer(pcbnew.B_Cu); z.SetLayerSet(ls)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(True); z.SetDoNotAllowVias(True)
    z.SetDoNotAllowZoneFills(fills)
    o = z.Outline(); o.NewOutline()
    for cx, cy in corners: o.Append(vec(cx, cy))
    board.Add(z)

# ESP32 antenna keep-out (full-width bar; overhangs the top edge)
u4 = fp_by_ref.get("U4")
if u4:
    cbb = u4.GetCourtyard(pcbnew.F_CrtYd).BBox()
    kl, kt, kr = cbb.GetLeft()/MM, cbb.GetTop()/MM, cbb.GetRight()/MM
    kbot = min(p.GetBoundingBox().GetTop() for p in u4.Pads())/MM
    rule_area([(kl, kt-1), (kr, kt-1), (kr, kbot), (kl, kbot)])

# perimeter keep-out: keep tracks/vias 0.5mm inside the edge (honours the 0.5mm
# copper-to-edge rule). Doesn't block the GND pour (fills=False).
# The LEFT edge is carved around J1: the USB-C receptacle is an edge part whose
# pads sit ~0.3mm from the cut, so a keep-out strip there would trap USB_DM/CC2.
m = 0.5
perim = [[(x1, y1), (x2, y1), (x2, y1+m), (x1, y1+m)],             # top
         [(x1, y2-m), (x2, y2-m), (x2, y2), (x1, y2)],             # bottom
         [(x2-m, y1), (x2, y1), (x2, y2), (x2-m, y2)]]             # right
if j1:
    jb = [p.GetBoundingBox() for p in j1.Pads()]
    jy1 = min(bb.GetTop() for bb in jb)/MM - 0.5
    jy2 = max(bb.GetBottom() for bb in jb)/MM + 0.5
    perim += [[(x1, y1), (x1+m, y1), (x1+m, jy1), (x1, jy1)],      # left above J1
              [(x1, jy2), (x1+m, jy2), (x1+m, y2), (x1, y2)]]      # left below J1
else:
    perim += [[(x1, y1), (x1+m, y1), (x1+m, y2), (x1, y2)]]        # left (full)
for corners in perim:
    rule_area(corners, fills=False)

board.BuildConnectivity()
pcbnew.SaveBoard(OUT, board)
print(f"built: {len(fp_by_ref)} fps, {board.GetNetCount()} nets, "
      f"outline {x2-x1:.0f}x{y2-y1:.0f}mm -> {OUT}")
