#!/usr/bin/env python3
"""Pack base + lid onto one print-ready plate and write a spec-compliant .3mf
(plain OPC/zip 3MF core spec) that Bambu Studio / OrcaSlicer parse cleanly.

Lid is flipped top-face-DOWN (correct print orientation); base stays floor-down.
Both laid flat on Z=0, side by side. Run after generate_enclosure.py."""
import zipfile, numpy as np, trimesh
from trimesh.transformations import rotation_matrix as rot

GAP = 8.0

def drop_to_plate(m, x0, y0):
    mn = m.bounds[0]
    m.apply_translation([x0 - mn[0], y0 - mn[1], -mn[2]])
    return m

base = trimesh.load("base.stl")
lid  = trimesh.load("lid.stl")
lid.apply_transform(rot(np.pi, [1, 0, 0]))        # flip top-face-down
drop_to_plate(base, 0, 0)
drop_to_plate(lid, 0, base.bounds[1][1] + GAP)

parts = [("base", base), ("lid_print_top_down", lid)]

# ---- build 3D/3dmodel.model XML ----------------------------------------------
CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
obj_xml, item_xml = [], []
for i, (name, m) in enumerate(parts, start=1):
    v = "".join(f'<vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>'
                for x, y, z in m.vertices)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>'
                for a, b, c in m.faces)
    obj_xml.append(f'<object id="{i}" type="model" name="{name}">'
                   f'<mesh><vertices>{v}</vertices>'
                   f'<triangles>{t}</triangles></mesh></object>')
    item_xml.append(f'<item objectid="{i}"/>')

model = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    f'<model unit="millimeter" xml:lang="en-US" xmlns="{CORE}">'
    '<metadata name="Application">esp32-ac-controller/generate_enclosure.py</metadata>'
    f'<resources>{"".join(obj_xml)}</resources>'
    f'<build>{"".join(item_xml)}</build>'
    '</model>')

content_types = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    '</Types>')

rels = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    '</Relationships>')

OUT = "ac_controller_enclosure.3mf"
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml", content_types)
    z.writestr("_rels/.rels", rels)
    z.writestr("3D/3dmodel.model", model)

foot = np.vstack([m.bounds for _, m in parts])
print(f"wrote {OUT}: parts={[n for n,_ in parts]}, "
      f"plate {foot[:,0].max()-foot[:,0].min():.1f} x {foot[:,1].max()-foot[:,1].min():.1f} mm")
