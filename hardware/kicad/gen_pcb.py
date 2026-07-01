import pcbnew, re, os, sys
SHARE = r"C:\Program Files\KiCad\10.0\share\kicad\footprints"
HERE  = r"C:\Users\marks\kicad_test"
net = open(os.path.join(HERE,"ac_controller.net"), encoding="utf-8").read()
comps = re.findall(r'\(comp\s*\(ref "([^"]+)"\).*?\(footprint "([^"]+)"\)', net, re.S)

board = pcbnew.BOARD()
MM = 1000000
def v(x_mm, y_mm): return pcbnew.VECTOR2I(int(x_mm*MM), int(y_mm*MM))

# place footprints in a grid
COLS, CW, CH, X0, Y0 = 7, 22, 19, 25, 25
placed, missed = 0, []
maxx = maxy = 0
for i,(ref,fp) in enumerate(comps):
    lib, name = fp.split(":")
    f = pcbnew.FootprintLoad(os.path.join(SHARE, lib+".pretty"), name)
    if f is None:
        missed.append(fp); continue
    f.SetReference(ref)
    col, row = i % COLS, i // COLS
    x, y = X0 + col*CW, Y0 + row*CH
    f.SetPosition(v(x, y))
    board.Add(f); placed += 1
    maxx, maxy = max(maxx, x), max(maxy, y)

# board outline (Edge.Cuts rectangle) around the placement
x1, y1, x2, y2 = 10, 10, maxx+CW, maxy+CH
rect = pcbnew.PCB_SHAPE(board)
rect.SetShape(pcbnew.SHAPE_T_RECT)
rect.SetStart(v(x1,y1)); rect.SetEnd(v(x2,y2))
rect.SetLayer(pcbnew.Edge_Cuts); rect.SetWidth(int(0.15*MM))
board.Add(rect)

out = os.path.join(HERE,"ac_controller.kicad_pcb")
pcbnew.SaveBoard(out, board)
print(f"placed={placed} missed={missed} outline={x2-x1}x{y2-y1}mm -> {out}")
