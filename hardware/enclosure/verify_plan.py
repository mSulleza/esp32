#!/usr/bin/env python3
"""Top-view sanity plot: lid openings overlaid on real component centres.
Confirms the IR aperture clears U6+D3 and that holes land on their parts.
Writes enclosure_plan.png. Run after generate_enclosure.py."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch, Circle
import generate_enclosure as g

fig, ax = plt.subplots(figsize=(9, 6.5))

# mounting ears
if g.MOUNT_EARS:
    cy = g.OUTY/2
    ax.add_patch(FancyBboxPatch((-g.EAR_REACH, cy-g.EAR_W/2), g.EAR_REACH+g.WALL, g.EAR_W,
                 boxstyle="round,pad=0,rounding_size=3", fc="0.85", ec="0.4", lw=1))
    ax.add_patch(FancyBboxPatch((g.OUTX-g.WALL, cy-g.EAR_W/2), g.EAR_REACH+g.WALL, g.EAR_W,
                 boxstyle="round,pad=0,rounding_size=3", fc="0.85", ec="0.4", lw=1))
    ax.add_patch(Circle((-g.EAR_REACH+g.EAR_HOLE_R+2.5, cy), g.EAR_HOLE_R, fc="white", ec="0.3"))
    ax.add_patch(Circle((g.OUTX+g.EAR_REACH-g.EAR_HOLE_R-2.5, cy), g.EAR_HOLE_R, fc="white", ec="0.3"))

# base outer + inner cavity
ax.add_patch(Rectangle((0, 0), g.OUTX, g.OUTY, fill=False, ec="black", lw=2))
ax.add_patch(Rectangle((g.WALL, g.WALL), g.OUTX-2*g.WALL, g.OUTY-2*g.WALL,
                       fill=False, ec="0.6", ls="--", lw=1))
# PCB outline
ax.add_patch(Rectangle((g.ORG_X, g.ORG_Y), g.BOARD_W, g.BOARD_H,
                       fill=True, fc="#2e7d32", alpha=0.12, ec="#2e7d32", lw=1.2))

# IR aperture (open window)
ax.add_patch(FancyBboxPatch((52, 12), 14, 26,
             boxstyle="round,pad=0,rounding_size=3",
             fc="#ff5252", alpha=0.25, ec="#d50000", lw=1.5))
ax.text(59, 25, "IR\nWINDOW\n(open)", ha="center", va="center",
        color="#b71c1c", fontsize=9, fontweight="bold")

# components
def mark(pt, label, c="#1565c0", r=1.6):
    ax.add_patch(Circle(pt, r, fc=c, ec="black", lw=0.5, zorder=5))
    ax.annotate(label, pt, textcoords="offset points", xytext=(4, 4),
                fontsize=8, fontweight="bold")
mark(g.U6, "U6 IR-RX", "#6a1b9a"); mark(g.D3, "D3 IR-TX", "#6a1b9a")
mark(g.U5, "U5 SHT40", "#00838f")
mark(g.J1, "J1 USB-C", "#ef6c00")
mark(g.SW1, "EN"); mark(g.SW2, "BOOT")
mark(g.D1, "D1", "#2e7d32"); mark(g.D2, "D2", "#1565c0")

# lid holes
for pt, rr in [(g.SW1, 1.9), (g.SW2, 1.9)]:
    ax.add_patch(Circle(pt, rr, fill=False, ec="black", ls=":", lw=1))
for pt in (g.D1, g.D2):
    ax.add_patch(Circle(pt, 1.3, fill=False, ec="black", ls=":", lw=1))
for vy in (g.U5[1]+0.7, g.U5[1]+2.7):
    ax.add_patch(FancyBboxPatch((g.U5[0]-0.5-4.5, vy-0.8), 9.0, 1.6,
                 boxstyle="round,pad=0,rounding_size=0.8",
                 fc="#90caf9", ec="#1565c0", lw=0.8))

# USB-C wall hole
ax.add_patch(Rectangle((-1, g.J1[1]-6), g.ORG_X+5, 12, fc="#ffe0b2",
                       ec="#ef6c00", lw=1, alpha=0.6))

ax.set_xlim(-g.EAR_REACH-4, g.OUTX+g.EAR_REACH+4); ax.set_ylim(g.OUTY+4, -4)  # y-down
ax.set_aspect("equal"); ax.set_title(
    "AC Controller enclosure — lid features over board (top view, y-down)")
ax.set_xlabel("X (mm)"); ax.set_ylabel("Y (mm)")
ax.grid(True, ls=":", alpha=0.4)
fig.tight_layout(); fig.savefig("enclosure_plan.png", dpi=130)
print("wrote enclosure_plan.png")
