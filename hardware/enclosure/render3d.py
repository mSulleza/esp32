#!/usr/bin/env python3
"""Headless, CLEAN shaded preview of base.stl + lid.stl -> enclosure_3d.png.
Per-face lighting, no wireframe edges (so flat faces look flat, not triangulated)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np, trimesh

LIGHT = np.array([0.4, -0.5, 0.8]); LIGHT = LIGHT / np.linalg.norm(LIGHT)

def add(ax, path, dz, rgb):
    m = trimesh.load(path)
    v = m.vertices.copy(); v[:, 2] += dz
    tris = v[m.faces]
    # flat shading: face brightness from angle to the light
    shade = np.clip(m.face_normals @ LIGHT, 0, 1) * 0.75 + 0.25
    cols = np.clip(np.array(rgb)[None, :] * shade[:, None], 0, 1)
    pc = Poly3DCollection(tris, facecolors=cols, edgecolor="none")
    pc.set_zsort("average")
    ax.add_collection3d(pc)
    return v

fig = plt.figure(figsize=(11, 7))
ax = fig.add_subplot(111, projection="3d")
v1 = add(ax, "base.stl", 0,  (0.42, 0.62, 0.82))
v2 = add(ax, "lid.stl", 24, (0.90, 0.66, 0.42))   # lifted to show the join
allv = np.vstack([v1, v2])

mn, mx = allv.min(0), allv.max(0)
ctr = (mn+mx)/2; span = (mx-mn).max()/2
for s, c in zip("xyz", ctr):
    getattr(ax, f"set_{s}lim")(c-span, c+span)
ax.set_box_aspect((1, 1, 1)); ax.view_init(elev=24, azim=-58)
ax.set_axis_off()
ax.set_title("AC Controller enclosure — exploded (lid above base)")
fig.tight_layout(); fig.savefig("enclosure_3d.png", dpi=140)
print("wrote enclosure_3d.png")
