#!/usr/bin/env python3
r"""
Parametric 3D-printable enclosure for the ESP32 Smart AC Controller PCB.

Two parts, friction (drop-over) fit, no supports required on a Bambu A1 mini:
  * base.stl  -- tray: floor, walls, PCB shelf, USB-C cutout, sensor vents
  * lid.stl   -- cap : top plate, drop-over skirt, IR aperture, vents,
                 button/LED access holes, PCB hold-down bosses

Design intent / hard constraints (from the routed board, fab-sht40):
  * IR emitter D3 (57.99, 33.0) and IR receiver U6 (55.0, 21.0) sit on the
    right end and fire PERPENDICULAR to the PCB top face. They get one large
    OPEN aperture in the lid directly above them -- no plastic in the optical
    path (PLA strongly attenuates ~940nm IR; an open window is the only way to
    guarantee performance). The tall IR-RX module may even protrude through it.
  * USB-C (J1) is an edge receptacle on the LEFT board edge -> hole in left wall.
  * SHT40 (U5, 55.0, 38.0) is the temp/RH sensor -> dedicated vents (lid + walls)
    so it reads ambient air, not the box's self-heated interior.
  * ESP32 (U4) PCB antenna overhangs the TOP edge -> extra clearance, no metal,
    no vents on that wall.

Coordinates: KiCad layout frame (x right, y DOWN). CPL "Mid Y" = -y.
Run:  python3 generate_enclosure.py        # writes base.stl, lid.stl
"""
import numpy as np
import trimesh
from trimesh.creation import box, cylinder
from trimesh import boolean

ENGINE = "manifold"
EPS = 0.01

# ---------------------------------------------------------------- board geometry
# Edge.Cuts rectangle from fab-sht40/ac_controller.kicad_pcb (KiCad mm, y-down).
BRD_MINX, BRD_MINY = -1.27, 4.18133
BRD_MAXX, BRD_MAXY = 63.906156, 43.437019
BOARD_W = BRD_MAXX - BRD_MINX          # ~65.18
BOARD_H = BRD_MAXY - BRD_MINY          # ~39.26

# ------------------------------------------------------------------ wall budget
WALL        = 2.0     # side wall thickness
FLOOR       = 2.0     # base floor thickness
TOP         = 2.0     # lid top-plate thickness
STANDOFF    = 3.0     # floor-top -> PCB bottom (clears bottom-side vias/solder)
PCB_T       = 1.6     # PCB thickness
HEAD        = 6.0     # PCB top -> lid underside (tallest part is USB-C ~3.2mm;
                      #   the taller IR-RX module pokes up into the open aperture)
LEDGE_W     = 1.2     # PCB support shelf width (board overlaps it by LEDGE_W-clear)

# per-edge clearance: board edge -> inner wall face
CLR_L, CLR_R, CLR_B = 0.4, 0.4, 0.4
CLR_T   = 3.0         # TOP edge = ESP32 antenna -> extra RF breathing room

# lid drop-over skirt
SKIRT_CLR   = 0.2     # gap between skirt inner and base outer (snug friction)
SKIRT_T     = 1.8
SKIRT_DEPTH = 4.0

# optional stick-on IR-filter recess (aperture stays open through the middle; this
# just adds a flush shelf on the OUTSIDE so a thin IR-pass window can be dropped in)
IR_FILTER_RECESS = True
FILT_DEPTH  = 1.2     # recess depth from the top face
FILT_LIP    = 1.5     # shelf width around the aperture (filter rests on it)

# optional wall-mount ears (flat tabs at floor level on the left + right walls)
MOUNT_EARS  = True
EAR_REACH   = 9.0     # how far each ear sticks out past the wall
EAR_W       = 13.0    # ear width (along the wall)
EAR_T       = 3.0     # ear thickness (floor level)
EAR_HOLE_R  = 2.2     # screw clearance (Ø4.4 -> M4 / #8)

# ------------------------------------------------------------------ derived Z's
PCB_BOT_Z = FLOOR + STANDOFF          # 5.0
PCB_TOP_Z = PCB_BOT_Z + PCB_T         # 6.6
BASE_TOP  = PCB_TOP_Z + HEAD          # 12.6  (= lid underside)
OUTER_TOP = BASE_TOP + TOP            # 14.6

# ------------------------------------------------------------------ derived XY
INNER_X = BOARD_W + CLR_L + CLR_R
INNER_Y = BOARD_H + CLR_T + CLR_B
OUTX = INNER_X + 2 * WALL
OUTY = INNER_Y + 2 * WALL

# board-local (0,0) -> model coords (origin at base outer min corner)
ORG_X = WALL + CLR_L                   # 2.4
ORG_Y = WALL + CLR_T                   # 5.0

def cpl(midx, midy):
    """JLC CPL (Mid X, Mid Y) -> model XY on the lid/base plan."""
    kx, ky = midx, -midy               # CPL Mid Y is negated KiCad y
    bx, by = kx - BRD_MINX, ky - BRD_MINY
    return ORG_X + bx, ORG_Y + by

# component centres we must respect (from fab-sht40/ac_controller_cpl.csv)
U6 = cpl(55.0, -21.0)      # IR receiver
D3 = cpl(57.985, -33.0)    # IR emitter LED
U5 = cpl(55.0, -38.0)      # SHT40 temp/RH
J1 = cpl(3.54, -20.0)      # USB-C centre (mouth is at left board edge)
SW1 = cpl(10.5, -9.0)      # EN button
SW2 = cpl(23.25, -25.8875) # BOOT button
D1 = cpl(5.617, -9.3214)   # power LED
D2 = cpl(44.1152, -34.4144)# status LED

# ---------------------------------------------------------------------- helpers
def bx(x0, x1, y0, y1, z0, z1):
    """Axis-aligned box from two opposite corners."""
    ext = (x1 - x0, y1 - y0, z1 - z0)
    T = trimesh.transformations.translation_matrix(
        ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    return box(extents=ext, transform=T)

def cyl(x, y, z0, z1, r, sec=64):
    T = trimesh.transformations.translation_matrix((x, y, (z0 + z1) / 2))
    return cylinder(radius=r, height=(z1 - z0), sections=sec, transform=T)

def rrect(cx, cy, w, h, z0, z1, r):
    """Rounded-rectangle (stadium when a side == 2r) prism."""
    r = min(r, w/2, h/2)
    parts = []
    if w - 2*r > EPS:
        parts.append(bx(cx - w/2 + r, cx + w/2 - r, cy - h/2, cy + h/2, z0, z1))
    if h - 2*r > EPS:
        parts.append(bx(cx - w/2, cx + w/2, cy - h/2 + r, cy + h/2 - r, z0, z1))
    for sx in (-1, 1):
        for sy in (-1, 1):
            parts.append(cyl(cx + sx*(w/2 - r), cy + sy*(h/2 - r), z0, z1, r))
    return boolean.union(parts, engine=ENGINE)

def slot_x(cx, cy, length, width, z0, z1, r=None):
    """Slot whose long axis runs along X (opening through Z, i.e. in a top/floor)."""
    r = width/2 if r is None else r
    return rrect(cx, cy, length, width, z0, z1, r)

# ===================================================================== BASE ====
def build_base():
    outer = bx(0, OUTX, 0, OUTY, 0, BASE_TOP)

    # wall-mount ears: flat tabs at floor level on the left + right walls. Floor
    # sits flat against the wall, lid (IR face) points into the room.
    adds, ear_holes = [outer], []
    if MOUNT_EARS:
        cy = OUTY / 2
        for side, x0, x1, hx in (
            ("L", -EAR_REACH, WALL,            -EAR_REACH + EAR_HOLE_R + 2.5),
            ("R", OUTX-WALL,  OUTX + EAR_REACH,  OUTX + EAR_REACH - EAR_HOLE_R - 2.5)):
            adds.append(rrect((x0+x1)/2, cy, x1-x0, EAR_W, 0, EAR_T, 3.0))
            ear_holes.append(cyl(hx, cy, -0.5, EAR_T + 0.5, EAR_HOLE_R))
    outer = boolean.union(adds, engine=ENGINE) if len(adds) > 1 else outer

    # hollow: full cavity above the shelf, narrower cavity below it (leaves shelf)
    cav_up = bx(WALL, OUTX-WALL, WALL, OUTY-WALL, PCB_BOT_Z, BASE_TOP + EPS)
    cav_lo = bx(WALL+LEDGE_W, OUTX-WALL-LEDGE_W, WALL+LEDGE_W, OUTY-WALL-LEDGE_W,
                FLOOR, PCB_BOT_Z + EPS)
    cuts = [cav_up, cav_lo]

    # USB-C hole in the LEFT wall (mouth at board left edge, centred on J1 y)
    uy = J1[1]
    cuts.append(bx(-1.0, ORG_X + 4.0, uy - 6.0, uy + 6.0, PCB_BOT_Z, PCB_BOT_Z + 6.0))

    # SHT40 vents -- RIGHT wall, low (below the lid skirt), near U5 corner
    for vy in (U5[1] - 4.0, U5[1] - 1.0, U5[1] + 2.0):
        cuts.append(bx(OUTX-WALL-EPS, OUTX+1.0, vy-1.0, vy+1.0, 5.5, 7.3))
    # general airflow -- BOTTOM wall slot row (also feeds the sensor corner)
    for vx in np.linspace(OUTX*0.30, OUTX*0.80, 5):
        cuts.append(bx(vx-2.5, vx+2.5, OUTY-WALL-EPS, OUTY+1.0, 5.5, 7.3))

    base = boolean.difference([outer] + cuts + ear_holes, engine=ENGINE)
    return base

# ===================================================================== LID =====
def build_lid():
    lox0, lox1 = -(SKIRT_CLR+SKIRT_T), OUTX + (SKIRT_CLR+SKIRT_T)
    loy0, loy1 = -(SKIRT_CLR+SKIRT_T), OUTY + (SKIRT_CLR+SKIRT_T)

    plate = bx(lox0, lox1, loy0, loy1, BASE_TOP, OUTER_TOP)

    # drop-over skirt (ring) hanging below the plate, wrapping the base outside
    sk_out = bx(lox0, lox1, loy0, loy1, BASE_TOP - SKIRT_DEPTH, BASE_TOP + EPS)
    sk_in  = bx(-SKIRT_CLR, OUTX + SKIRT_CLR, -SKIRT_CLR, OUTY + SKIRT_CLR,
                BASE_TOP - SKIRT_DEPTH - EPS, BASE_TOP + 2*EPS)
    skirt = boolean.difference([sk_out, sk_in], engine=ENGINE)

    add = [plate, skirt]

    # PCB hold-down bosses: press the board onto the base shelf at 4 clear corners
    for (px, py) in [(ORG_X+3, ORG_Y+3), (ORG_X+BOARD_W-3, ORG_Y+3),
                     (ORG_X+3, ORG_Y+BOARD_H-3), (ORG_X+BOARD_W-3, ORG_Y+BOARD_H-3)]:
        add.append(cyl(px, py, PCB_TOP_Z, BASE_TOP + EPS, 2.2))
    lid = boolean.union(add, engine=ENGINE)

    cuts = []
    pz0, pz1 = BASE_TOP - 0.5, OUTER_TOP + 0.5      # through the top plate

    # ---- IR aperture: ONE open window over U6 + D3 (the whole point) ----
    ix0, ix1 = 52.0, 66.0
    iy0, iy1 = 12.0, 38.0
    icx, icy = (ix0+ix1)/2, (iy0+iy1)/2
    iw, ih = ix1-ix0, iy1-iy0
    cuts.append(rrect(icx, icy, iw, ih, pz0, pz1, 3.0))
    # flush recess on the OUTSIDE so an optional stick-on IR-pass window seats level
    if IR_FILTER_RECESS:
        cuts.append(rrect(icx, icy, iw + 2*FILT_LIP, ih + 2*FILT_LIP,
                          OUTER_TOP - FILT_DEPTH, pz1, 3.0 + FILT_LIP))

    # ---- SHT40 vents in the lid, just below the IR window ----
    for vy in (U5[1] + 0.7, U5[1] + 2.7):
        cuts.append(slot_x(U5[0]-0.5, vy, 9.0, 1.6, pz0, pz1))

    # ---- button access (paperclip) over EN / BOOT ----
    for (bxp, byp) in (SW1, SW2):
        cuts.append(cyl(bxp, byp, pz0, pz1, 1.9))
    # ---- LED light holes over power / status ----
    for (lx, ly) in (D1, D2):
        cuts.append(cyl(lx, ly, pz0, pz1, 1.3))

    # ---- notch the skirt so it never covers the USB-C mouth ----
    uy = J1[1]
    cuts.append(bx(lox0-0.5, ORG_X+4.0, uy-6.5, uy+6.5,
                   BASE_TOP - SKIRT_DEPTH - 0.5, BASE_TOP))
    # ---- notch the skirt over the right-wall + bottom-wall vents (low slots are
    #      below the skirt, but keep the skirt clear above them for airflow) ----
    cuts.append(bx(OUTX - 12, OUTX + (SKIRT_CLR+SKIRT_T) + 0.5,
                   U5[1]-5, U5[1]+4, BASE_TOP - SKIRT_DEPTH - 0.5, BASE_TOP - 1.2))

    lid = boolean.difference([lid] + cuts, engine=ENGINE)
    return lid

# ========================================================================= main
def report(name, m):
    ok = m.is_watertight and m.is_winding_consistent
    e = m.bounding_box.extents
    print(f"  {name:5s}  watertight={m.is_watertight} winding={m.is_winding_consistent} "
          f"tris={len(m.faces):5d}  bbox={e[0]:.1f} x {e[1]:.1f} x {e[2]:.1f} mm  "
          f"vol={m.volume/1000:.1f} cm^3")
    return ok

if __name__ == "__main__":
    ears_w = OUTX + 2*EAR_REACH if MOUNT_EARS else OUTX
    print(f"board {BOARD_W:.2f} x {BOARD_H:.2f} mm  ->  "
          f"base body {OUTX:.1f} x {OUTY:.1f} x {BASE_TOP:.1f} mm "
          f"(across ears {ears_w:.1f} mm),  outer height {OUTER_TOP:.1f} mm")
    if IR_FILTER_RECESS:
        print(f"IR-filter recess: {14+2*FILT_LIP:.1f} x {26+2*FILT_LIP:.1f} mm, "
              f"{FILT_DEPTH:.1f} mm deep  -> filter window <= "
              f"{14+2*FILT_LIP-0.5:.1f} x {26+2*FILT_LIP-0.5:.1f} mm")
    print(f"IR aperture covers  U6{tuple(round(v,1) for v in U6)}  "
          f"D3{tuple(round(v,1) for v in D3)}")

    base = build_base()
    lid  = build_lid()
    allok = report("base", base) & report("lid", lid)

    base.export("base.stl")
    lid.export("lid.stl")
    print("wrote base.stl, lid.stl" + ("" if allok else "  [WARN: non-manifold!]"))
