# -*- coding: utf-8 -*-
"""Quick integration smoke test for the full visu pipeline."""

import os
import sys
import tempfile

sys.path.insert(0, ".")

from cli.visu import builder, catalog, gvl, screen_xml, svg_export, svg_import, themes

# 1. Parse SVG with variables
svg = """<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200" viewBox="0 0 400 200">
  <defs><style>:root{ --surface:#1e1e1e; --primary:#0078d4; }</style></defs>
  <text x="20" y="30" font-size="14"
        data-cds-type="textfield" data-width="150" data-height="24"
        data-text-var="HMI.Temperature">%.1f C</text>
  <rect x="20" y="60" width="120" height="40"
        data-cds-type="button" data-text="Start" data-cds-tap="TAP HMI.StartPump"/>
</svg>"""

result = svg_import.parse_svg(svg)
print("Parsed", len(result["elements"]), "elements")
assert len(result["elements"]) == 2

# 2. GVL detection
vars_detected = gvl.collect_variables(result["elements"])
print("Detected vars:", vars_detected)
assert "HMI.Temperature" in vars_detected
assert "HMI.StartPump" in vars_detected

# 3. Full GVL file flow
with tempfile.TemporaryDirectory() as td:
    pou_dir = os.path.join(td, "POUs")
    os.makedirs(pou_dir)

    gvl_path = gvl.ensure_gvl(td, result["elements"], gvl_name="VisuVars")
    assert gvl_path is not None
    with open(gvl_path) as f:
        content = f.read()
        assert "Temperature" in content
        assert "StartPump" in content
    print("GVL file created:", gvl_path)

    # Second call skips duplicates
    gvl_path2 = gvl.ensure_gvl(td, result["elements"], gvl_name="VisuVars")
    assert gvl_path2 == gvl_path
    print("Duplicate prevention works")

# 4. Build screen XML with elements
xml = builder.build_screen(
    name="IntegrationTest",
    size_x=400,
    size_y=200,
    parent_guid="aed6d2f4-6485-4017-982c-3b2fa7b0b4be",
    parent_svnode_guid="ddc05353-f826-4861-84cf-5fd88f7a319e",
    path_segments=["HMI"],
)

# Add a rectangle
rect_cat = catalog.load_catalog("rectangle")
xml, geom, info = builder.append_element(
    xml,
    rect_cat,
    {"x": "10", "y": "10", "width": "100", "height": "50"},
    theme_colors=themes.load_theme("flat-style"),
)
assert geom["x"] == 10

# 5. screen_xml read back
elems = screen_xml.list_elements(xml)
assert len(elems) == 1
assert elems[0]["x"] == "10"

sx, sy = screen_xml.read_screen_size(xml)
assert (sx, sy) == (400, 200)

# 6. svg_export reverse
svg_out = svg_export.screen_to_svg(xml)
assert "<svg" in svg_out
assert "</svg>" in svg_out

print("ALL INTEGRATION TESTS PASSED")
