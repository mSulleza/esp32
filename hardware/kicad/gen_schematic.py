#!/usr/bin/env python3
"""
Generate an ERC-clean KiCad 10 schematic for the integrated ESP32 AC controller.

Approach (validated): place each component at rotation 0 and connect every pin
with a GLOBAL LABEL dropped exactly on the pin's endpoint. Matching net names =
connected nets (no drawn wires needed). Real pin geometry is read from the
installed KiCad symbol libraries so coordinates are exact. Unconnected pins get
no-connect flags; power nets get PWR_FLAG so ERC's "driven" check passes.

Run:
    python3 gen_schematic.py            # writes ac_controller.kicad_sch
Then validate (Windows kicad-cli works from WSL):
    kicad-cli sch erc ac_controller.kicad_sch
    kicad-cli sch export netlist ac_controller.kicad_sch

Override the symbol dir with env KICAD_SYMBOL_DIR if needed.
"""
import re, os, sys

SYMDIR = os.environ.get("KICAD_SYMBOL_DIR",
    "/mnt/c/Program Files/KiCad/10.0/share/kicad/symbols")

# ---------------- symbol library reader (follows `extends`) ----------------
_LIBS = {}
def _load(lib):
    if lib in _LIBS: return _LIBS[lib]
    with open(os.path.join(SYMDIR, lib + ".kicad_sym"), encoding="utf-8") as f:
        lines = f.readlines()
    idx = {}; i = 0
    while i < len(lines):
        m = re.match(r'\t\(symbol "([^"]+)"', lines[i])
        if m:
            start = i; end = len(lines)
            for j in range(i + 1, len(lines)):
                if re.match(r'\t\(symbol "', lines[j]): end = j; break
            idx[m.group(1)] = lines[start:end]; i = end; continue
        i += 1
    _LIBS[lib] = idx; return idx

def _block(lib, name): return _load(lib).get(name)
def _extends(blk):
    for l in blk[:25]:
        m = re.search(r'\(extends "([^"]+)"', l)
        if m: return m.group(1)
    return None

def geom_block(lib, name):
    """Return (geom_name, block_lines) following extends to the part with pins."""
    b = _block(lib, name)
    if b is None: raise KeyError(f"{lib}:{name} not found")
    p = _extends(b)
    return geom_block(lib, p) if p else (name, b)

def pins(lib, name):
    _, b = geom_block(lib, name)
    out = []; i = 0
    while i < len(b):
        if re.search(r'\(pin \w+ \w+', b[i]):
            seg = "".join(b[i:i + 22])
            at = re.search(r'\(at ([\-0-9.]+) ([\-0-9.]+) ([0-9]+)', seg)
            nm = re.search(r'\(name "([^"]*)"', seg)
            num = re.search(r'\(number "([^"]*)"', seg)
            if at and num:
                out.append({"num": num.group(1), "name": nm.group(1) if nm else "",
                            "x": float(at.group(1)), "y": float(at.group(2)),
                            "rot": int(at.group(3))})
        i += 1
    return out

def flat_symbol(lib_id, lib, name):
    """Embed a standalone symbol under lib_id, using the geom block's drawing.
    Renames the top symbol AND its child sub-symbols (<geom>_u_s) to the lib_id
    prefix so KiCad accepts the flattened (extends-resolved) definition."""
    gn, b = geom_block(lib, name)
    res = []
    for k, l in enumerate(b):
        if k == 0:
            l = re.sub(r'\(symbol "[^"]+"', f'(symbol "{lib_id}"', l, count=1)
        else:
            # child units must be named "<bare-part-name>_u_s" (no lib prefix);
            # for extends-resolved parts the parent geom name differs from `name`.
            l = l.replace(f'(symbol "{gn}_', f'(symbol "{name}_')
        res.append(l)
    return res

# ---------------- uuid helper (deterministic) ----------------
_uc = [0]
def uuid():
    _uc[0] += 1
    h = f"{_uc[0]:032x}"
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
ROOT = uuid()

def snap(v):
    """Snap to KiCad's 1.27 mm connection grid so endpoints aren't 'off grid'."""
    return round(round(v / 1.27) * 1.27, 2)

# ---------------- design definition ----------------
# (ref, lib, symbol, value, footprint, x, y)
COMPONENTS = [
    ("J1","Connector","USB_C_Receptacle_USB2.0_16P","USB-C","Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",120,140),
    ("U1","Power_Protection","USBLC6-2SC6","USBLC6-2SC6","Package_TO_SOT_SMD:SOT-23-6",120,300),
    ("U2","Regulator_Linear","AMS1117-3.3","AMS1117-3.3","Package_TO_SOT_SMD:SOT-223-3_TabPin2",120,440),
    ("U3","Interface_USB","CH340C","CH340C","Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",320,140),
    ("U4","RF_Module","ESP32-WROOM-32E","ESP32-WROOM-32E","RF_Module:ESP32-WROOM-32E",560,160),
    ("U5","Sensor_Humidity","SHT4x","SHT40","Sensor_Humidity:Sensirion_DFN-4_1.5x1.5mm_P0.8mm_SHT4x_NoCentralPad",820,160),  # SHT40 temp+humidity, I2C 0x44 (cheaper than BME280)
    # IRM-H638T pinout (per datasheet): 1=GND 2=GND 3=OUT 4=Vcc. Use a generic
    # 4-pin symbol numbered 1-4 so pads map to the real functions (the Vishay TSOP
    # symbol's OUT=1 numbering does NOT match this part).
    ("U6","Connector_Generic","Conn_01x04","IR-RX-38kHz","OptoDevice:Everlight_IRM-H6xxT",820,340),
    ("Q1","Transistor_BJT","MMBT3904","MMBT3904","Package_TO_SOT_SMD:SOT-23",320,320),
    ("Q2","Transistor_BJT","MMBT3904","MMBT3904","Package_TO_SOT_SMD:SOT-23",320,440),
    ("Q3","Transistor_BJT","MMBT3904","MMBT3904","Package_TO_SOT_SMD:SOT-23",560,440),  # was MMBT2222A; 3904 Basic, same SOT-23 B/E/C, handles ~76mA pulsed IR LED
]
# passives auto-placed on a grid below y=560
PASSIVES = [
    ("R_EN","R","10k"), ("R_IO0","R","10k"), ("R_SDA","R","4.7k"), ("R_SCL","R","4.7k"),
    ("R_CC1","R","5.1k"), ("R_CC2","R","5.1k"), ("R_base","R","1k"), ("R_led","R","47"),
    ("R_led2","R","330"), ("R_pwr","R","1k"), ("R_irrx","R","100"),
    ("C1","C","10uF"), ("C3","C","10uF"), ("C4","C","100nF"), ("C5","C","100nF"),
    ("C6","C","100nF"), ("C7","C","10uF"), ("C8","C","100nF"), ("C_EN","C","1uF"),
    ("C_irrx","C","4.7uF"),
    ("D1","LED","Green"), ("D2","LED","Blue"),
    ("SW1","SW_Push","EN"), ("SW2","SW_Push","BOOT"),
    ("D3","IRLED","IR-940nm"),
]
PASS_LIB = {"R":("Device","R","Resistor_SMD:R_0603_1608Metric"),
            "C":("Device","C","Capacitor_SMD:C_0603_1608Metric"),
            "LED":("Device","LED","LED_SMD:LED_0603_1608Metric"),
            "SW_Push":("Switch","SW_Push","Button_Switch_SMD:SW_Push_1P1T_NO_CK_KMR2"),
            "IRLED":("Device","LED","LED_SMD:LED_Everlight-SMD3528_3.5x2.8mm_67-21ST"),  # on-board SMD IR emitter (C60109 IR67-21C = SMD3528-2P)
            "Conn_01x02":("Connector_Generic","Conn_01x02","Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical")}

# Net map: net -> list of (ref, pin-identifier). Identifier matches pin NAME or NUMBER.
NETS = {
    "+5V": [("J1","VBUS"),("U1","VBUS"),("U2","VI"),("U3","VCC"),("R_led","1"),("R_pwr","1"),("C1","1")],
    # CH340C powered from 5V; its internal reg output V3 (3.3V) sets UART logic
    # level (safe for ESP32) and gets its own decoupling cap. V3 is a power
    # output, so it drives this net by itself (no PWR_FLAG, no LDO conflict).
    "VREG3": [("U3","V3"),("C5","1")],
    "+3V3": [("U2","VO"),("U4","VDD"),("U5","VDD"),
             ("R_EN","2"),("R_IO0","2"),("R_SDA","2"),("R_SCL","2"),("R_irrx","1"),
             ("C3","1"),("C4","1"),("C6","1"),("C7","1"),("C8","1")],
    "GND": [("J1","GND"),("J1","SHIELD"),("U1","GND"),("U2","GND"),("U3","GND"),("U4","GND"),
            ("U5","VSS"),("U6","1"),("U6","2"),("Q3","E"),("R_CC1","2"),("R_CC2","2"),
            ("C1","2"),("C3","2"),("C4","2"),("C5","2"),("C6","2"),("C7","2"),("C8","2"),
            ("C_EN","2"),("C_irrx","2"),("D1","K"),("D2","K"),("SW1","2"),("SW2","2")],
    "USB_DP": [("J1","D+"),("U1","I/O1"),("U3","UD+")],
    "USB_DM": [("J1","D-"),("U1","I/O2"),("U3","UD-")],
    "CC1": [("J1","CC1"),("R_CC1","1")],
    "CC2": [("J1","CC2"),("R_CC2","1")],
    "UART_TX": [("U4","TXD0/IO1"),("U3","RXD")],
    "UART_RX": [("U4","RXD0/IO3"),("U3","TXD")],
    "DTR": [("U3","~{DTR}"),("Q1","E"),("Q2","B")],
    "RTS": [("U3","~{RTS}"),("Q2","E"),("Q1","B")],
    "EN":  [("U4","EN"),("R_EN","1"),("C_EN","1"),("SW1","1"),("Q2","C")],
    "IO0": [("U4","IO0"),("R_IO0","1"),("SW2","1"),("Q1","C")],
    "I2C_SDA": [("U4","IO21"),("U5","SDA"),("R_SDA","1")],
    "I2C_SCL": [("U4","IO22"),("U5","SCL"),("R_SCL","1")],
    "IR_RX": [("U4","IO14"),("U6","3")],       # U6 pad 3 = OUT
    "IR_TX_GATE": [("U4","IO4"),("R_base","1")],
    "IRTX_BASE": [("R_base","2"),("Q3","B")],
    "IR_LED_A": [("R_led","2"),("D3","2")],   # LED anode (pin 2 = A)
    "IR_LED_K": [("D3","1"),("Q3","C")],       # LED cathode (pin 1 = K)
    "IRRX_VCC": [("R_irrx","2"),("C_irrx","1"),("U6","4")],   # U6 pad 4 = Vcc
    "STATUS_LED": [("U4","IO2"),("R_led2","1")],
    "LED2A": [("R_led2","2"),("D2","A")],
    "LED1A": [("R_pwr","2"),("D1","A")],
}

# ---------------- build component table with resolved pins ----------------
# Auto-place everything on a uniform grid with cells big enough for the largest
# part (ESP32) plus its outward label fan, so nothing overlaps and it stays in
# the page. ICs first, then passives.
ITEMS = [(r,l,s,v,f) for (r,l,s,v,f,_x,_y) in COMPONENTS]
for ref,kind,val in PASSIVES:
    lib,sym,fp = PASS_LIB[kind]; ITEMS.append((ref,lib,sym,val,fp))

COLS, CW, CH, OX, OY = 6, 190.5, 152.4, 127.0, 101.6  # cell W/H, origin (grid mults)
ALL = []
for i,(ref,lib,sym,val,fp) in enumerate(ITEMS):
    c, r = i % COLS, i // COLS
    ALL.append({"ref":ref,"lib":lib,"sym":sym,"value":val,"fp":fp,
                "lib_id":f"{lib}:{sym}","x":snap(OX + c*CW),"y":snap(OY + r*CH),
                "pins":pins(lib,sym)})

# index pins by (ref, matcher)
def find_net(ref, pin):
    for net, members in NETS.items():
        for r, ident in members:
            if r == ref and (ident == pin["num"] or ident == pin["name"]):
                return net
    return None

# ---------------- emit schematic ----------------
def sx(c, p): return round(c["x"] + p["x"], 2)
def sy(c, p): return round(c["y"] - p["y"], 2)

out = []
out.append('(kicad_sch')
out.append('\t(version 20250114)')
out.append('\t(generator "eeschema")')
out.append('\t(generator_version "9.0")')
out.append(f'\t(uuid "{ROOT}")')
out.append('\t(paper "PAPER_PLACEHOLDER")')   # replaced once page bounds are known
# lib_symbols (unique)
out.append('\t(lib_symbols')
seen = {}
for c in ALL:
    if c["lib_id"] in seen: continue
    seen[c["lib_id"]] = True
    out += [l.rstrip("\n") for l in flat_symbol(c["lib_id"], c["lib"], c["sym"])]
# PWR_FLAG symbol
out += [l.rstrip("\n") for l in flat_symbol("power:PWR_FLAG","power","PWR_FLAG")]
out.append('\t)')

labels_at = {}   # coord -> net (dedup stacked pins)
nc_at = set()
bounds = [0.0, 0.0]            # running max (x, y) of any element, for page size
def note(x, y):
    if x > bounds[0]: bounds[0] = x
    if y > bounds[1]: bounds[1] = y

def emit_label_stub(net, sxx, syy, px, py, rot=0):
    """Wire stub from the pin endpoint radially outward + net label at the far end.
    Direction comes from the pin's ORIENTATION (rot), NOT its position vector: a
    tall/narrow symbol (e.g. the ESP32) has side pins whose position vector reads
    'more vertical' than horizontal, which made vertical stubs that ran COLLINEAR
    down one edge and overlapped (stub len 3.81 > 2.54 pin pitch), silently welding
    adjacent pins into one net. Radial-by-orientation stubs are parallel, never
    collinear, so they cannot overlap."""
    L = 3.81
    if rot in (0, 180):                      # horizontal pin -> stub left/right
        ux, uy = (1 if px >= 0 else -1), 0
    else:                                    # vertical pin -> stub up/down (sch. y flips)
        ux, uy = 0, (-1 if py >= 0 else 1)
    fx, fy = round(sxx + ux*L, 2), round(syy + uy*L, 2)
    out.append(f'\t(wire (pts (xy {sxx} {syy}) (xy {fx} {fy})) '
               f'(stroke (width 0) (type default)) (uuid "{uuid()}"))')
    if   ux == 1:  ang, just = 0, "left"
    elif ux == -1: ang, just = 0, "right"
    elif uy == -1: ang, just = 90, "left"
    else:          ang, just = 90, "right"
    out.append(f'\t(global_label "{net}" (shape bidirectional) (at {fx} {fy} {ang}) '
               f'(effects (font (size 1.27 1.27)) (justify {just})) (uuid "{uuid()}"))')
    tlen = len(net) * 1.8
    note(fx + (tlen if (ang == 0 and just == "left") else 0),
         fy + (tlen if (ang == 90 and just == "left") else 0))

def emit_symbol(c):
    s = []
    s.append('\t(symbol')
    s.append(f'\t\t(lib_id "{c["lib_id"]}")')
    s.append(f'\t\t(at {c["x"]} {c["y"]} 0)')
    s.append('\t\t(unit 1)')
    s.append('\t\t(exclude_from_sim no)(in_bom yes)(on_board yes)(dnp no)')
    s.append(f'\t\t(uuid "{uuid()}")')
    s.append(f'\t\t(property "Reference" "{c["ref"]}" (at {c["x"]+2} {c["y"]-2} 0)(effects (font (size 1.27 1.27))))')
    s.append(f'\t\t(property "Value" "{c["value"]}" (at {c["x"]+2} {c["y"]+2} 0)(effects (font (size 1.27 1.27))))')
    s.append(f'\t\t(property "Footprint" "{c["fp"]}" (at {c["x"]} {c["y"]} 0)(effects (font (size 1.27 1.27))(hide yes)))')
    for p in c["pins"]:
        s.append(f'\t\t(pin "{p["num"]}" (uuid "{uuid()}"))')
    s.append('\t\t(instances')
    s.append(f'\t\t\t(project "" (path "/{ROOT}" (reference "{c["ref"]}") (unit 1)))')
    s.append('\t\t)')
    s.append('\t)')
    return s

for c in ALL:
    out += emit_symbol(c)
    note(c["x"], c["y"])
    for p in c["pins"]:
        net = find_net(c["ref"], p)
        sxx, syy = sx(c, p), sy(c, p)
        key = (sxx, syy)
        if net:
            if key in labels_at:
                continue                 # stacked pin (e.g. multi VBUS/GND) already labelled
            labels_at[key] = net
            emit_label_stub(net, sxx, syy, p["x"], p["y"], p["rot"])
        elif key not in nc_at:
            nc_at.add(key)
            out.append(f'\t(no_connect (at {sxx} {syy}) (uuid "{uuid()}"))')

# PWR_FLAGs on nets driven only by input pins (+5V from connector, GND,
# IRRX_VCC fed via R). +3V3/VREG3 are driven by real reg outputs -> no flag.
# Placed in a row below the component grid.
nrows = (len(ALL) + COLS - 1) // COLS
fy0 = snap(OY + nrows * CH)
for i,(net,fx) in enumerate({"+5V":snap(OX),"GND":snap(OX+CW),"IRRX_VCC":snap(OX+2*CW)}.items()):
    cx, cy = fx, fy0
    out.append('\t(symbol')
    out.append('\t\t(lib_id "power:PWR_FLAG")')
    out.append(f'\t\t(at {cx} {cy} 0)(unit 1)')
    out.append('\t\t(exclude_from_sim no)(in_bom yes)(on_board yes)(dnp no)')
    out.append(f'\t\t(uuid "{uuid()}")')
    out.append(f'\t\t(property "Reference" "#FLG{i}" (at {cx} {cy-3} 0)(effects (font (size 1 1))(hide yes)))')
    out.append(f'\t\t(property "Value" "PWR_FLAG" (at {cx} {cy+5} 0)(effects (font (size 1 1))))')
    out.append(f'\t\t(pin "1" (uuid "{uuid()}"))')
    out.append(f'\t\t(instances (project "" (path "/{ROOT}" (reference "#FLG{i}") (unit 1))))')
    out.append('\t)')
    emit_label_stub(net, cx, cy, 0.0, 0.0)
    note(cx, cy)

out.append(')')

# Size the page to fit everything (+ margin), then substitute the placeholder.
PW = round(bounds[0] + 30, 1); PH = round(bounds[1] + 30, 1)
out = [l.replace('"PAPER_PLACEHOLDER"', f'"User" {PW} {PH}') for l in out]

with open("ac_controller.kicad_sch","w",encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")

# coverage report
mapped = sum(1 for c in ALL for p in c["pins"] if find_net(c["ref"],p))
total = sum(len(c["pins"]) for c in ALL)
print(f"components={len(ALL)} pins={total} mapped={mapped} no_connect={total-mapped}")
print(f"nets={len(labels_at and NETS)} label_coords={len(labels_at)} nc_coords={len(nc_at)}")
# warn about net members that never matched a pin (typo catcher)
for net,members in NETS.items():
    for r,ident in members:
        c=next((x for x in ALL if x["ref"]==r),None)
        if not c: print(f"  !! net {net}: ref {r} not found"); continue
        if not any(ident==p["num"] or ident==p["name"] for p in c["pins"]):
            print(f"  !! net {net}: {r} has no pin '{ident}' (pins: {[p['name'] or p['num'] for p in c['pins']][:8]}...)")
print("wrote ac_controller.kicad_sch")
