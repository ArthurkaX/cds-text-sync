"""Argument registration for offline visualization commands."""

def register(subparsers):
        # -- visu subcommand (offline) ------------------------------------------
        p_visu = subparsers.add_parser(
            "visu",
            help="Generate and manage CODESYS visualization XML files",
            description="Offline commands to create screens and add elements. "
            "These write .xml files directly into project-view/ "
            "for later import via ``cts import``.",
            epilog="""
    from-svg SVG contract:
      Supported elements: rect, circle, ellipse, line, text,
        rect[data-cds-type=button], text[data-cds-type=textfield]

      Prefer a semantic class over a colour. class="..." expands through
      cds_text_sync/visu/stylesheet.css (override it with a project-level visu.css):
        surfaces   panel card divider
        type       h1 h2 value label caption   (the whole scale: 22/16/28/12/11)
        emphasis   muted inverse
        status     ok warn alarm
        P&ID       pipe-water metal

      CSS variables (set in a :root block, or use the class above):
        --screen       generated screen background
        --background   style background
        --surface      panel/background fill default
        --panel        sub-panel fill
        --card         inner surface, one step down from panel
        --border       --frame stroke default
        --divider      separator line
        --text         font colour
        --text-muted   muted/secondary font colour
        --primary      accent/highlight
        --secondary    secondary accent
        --success      green/ok
        --warning      orange/caution
        --error        red/alarm
        --water        pipe/fluid
        --water-dim    pipe/fluid outline
        --metal        structural elements

      Color rules for SVG attributes:
        - <text fill="..."> controls font colour (compiles to uint literal)
        - <rect fill="..."> controls background fill
        - <rect stroke="..."> controls frame/border colour
        - <button> and <textfield> colours: SVG fill/stroke controls
          browser preview but is IGNORED by the transpiler. These
          elements inherit the CODESYS project visual style.
          For coloured button-like shapes use plain <rect> + <text>.

      Look before you import:
        cts visu preview --svg screen.svg        # resolved SVG + PNG
        cts visu lint --svg screen.svg [--fix]   # grid, type scale, overflow

      Unsupported in v1: polygon, polyline, image, transform,
        gradients, filters, masks, animation, viewBox scaling,
        Table, ComboBox, TabControl, GroupBox, Checkbox, etc.
    """,
        )
        p_visu.add_argument(
            "visu_action",
            choices=[
                "new",
                "create-screen",
                "add",
                "list",
                "check",
                "types",
                "describe",
                "from-svg",
                "to-svg",
                "preview",
                "lint",
                "capture-frame",
            ],
            help="new - scaffold an editable SVG sketch from the seed template\n"
            "create-screen - create a new empty screen\n"
            "add - add an element to a screen\n"
            "list - list elements in a screen\n"
            "check - validate a screen\n"
            "types - list available element types\n"
            "describe - describe a type or element\n"
            "from-svg - compile SVG to CODESYS screen XML\n"
            "to-svg - decompile CODESYS screen XML to SVG\n"
            "preview - render an SVG sketch to a viewable SVG/PNG (resolved colours)\n"
            "lint - check an SVG sketch for layout/typography problems\n"
            "capture-frame - capture a VisuFbFrame instance as golden template + catalog",
        )
        p_visu.add_argument(
            "--sync-folder", default="", help="Sync folder or project-view dir"
        )
        p_visu.add_argument(
            "--name", default="", help="Screen name (for new, create-screen)"
        )
        p_visu.add_argument(
            "--folder",
            default="",
            help="CODESYS folder path e.g. Runtime/PLC Logic/Application/HMI",
        )
        p_visu.add_argument(
            "--width", type=int, default=800, help="Screen width (for new, create-screen)"
        )
        p_visu.add_argument(
            "--height",
            type=int,
            default=480,
            help="Screen height (for new, create-screen)",
        )
        p_visu.add_argument(
            "--start-visu",
            action="store_true",
            help="Set as start visualization (for create-screen)",
        )
        p_visu.add_argument("--screen", default="", help="Screen name or path")
        p_visu.add_argument("--visu", default="", help="Sub-visu name (for capture-frame)")
        p_visu.add_argument("--type", default="", help="Element type (for add, describe)")
        p_visu.add_argument("--x", type=int, help="X position (for add)")
        p_visu.add_argument("--y", type=int, help="Y position (for add)")
        p_visu.add_argument(
            "--w", type=int, help="Width (for add; also overrides --width for new)"
        )
        p_visu.add_argument(
            "--h", type=int, help="Height (for add; also overrides --height for new)"
        )
        p_visu.add_argument(
            "--shape",
            default="",
            help="Shape variant: rectangle|ellipse|rounded|line (for add)",
        )
        p_visu.add_argument(
            "--fill", default="", help="Fill color, 0xAARRGGBB or name (for add)"
        )
        p_visu.add_argument("--frame", default="", help="Frame color (for add)")
        p_visu.add_argument("--corner-radius", type=int, help="Corner radius (for add)")
        p_visu.add_argument("--border-width", type=int, help="Border width (for add)")
        p_visu.add_argument("--angle", type=int, help="Rotation angle (for add)")
        p_visu.add_argument("--tooltip", default="", help="Tooltip text (for add)")
        p_visu.add_argument(
            "--svg", default="", help="SVG file path (for from-svg, preview, lint)"
        )
        p_visu.add_argument(
            "--elem", type=int, help="Element index (for describe --screen --elem)"
        )
        p_visu.add_argument(
            "--theme",
            default="flat-style",
            help=(
                "CODESYS style preset (for from-svg, preview, lint): "
                "flat-style|basic-style|default|white-style|style-2..."
            ),
        )
        p_visu.add_argument(
            "--out",
            default="",
            help="Output path (for new, from-svg, to-svg, preview)",
        )
        p_visu.add_argument(
            "--create-screen",
            action="store_true",
            help="Create a new screen when compiling SVG (for from-svg)",
        )
        p_visu.add_argument(
            "--screen-name", default="", help="Screen name when --create-screen is used"
        )
        p_visu.add_argument(
            "--replace",
            action="store_true",
            help=(
                "Recompile an existing screen from the sketch, keeping its object "
                "Guid (for from-svg --create-screen)"
            ),
        )
        p_visu.add_argument(
            "--gvl",
            default="",
            help="GVL name for auto-generated declarations (e.g. VisuVars)",
        )
        p_visu.add_argument(
            "--gvl-file",
            default="",
            help="Explicit GVL .st file path",
        )
        p_visu.add_argument(
            "--background",
            default="",
            help=(
                "Screen background (for from-svg, preview, lint): "
                "auto (curated neutral, default) | style (the project style's own "
                "background) | #RRGGBB"
            ),
        )
        p_visu.add_argument(
            "--scheme",
            default="",
            choices=["", "light", "dark"],
            help=(
                "Colour scheme (for new, from-svg, preview, lint): light (default) "
                "| dark. 'visu new' records it as data-cds-scheme on the sketch; "
                "elsewhere it overrides that attribute for a single render"
            ),
        )
        p_visu.add_argument(
            "--no-preview",
            action="store_true",
            help="Skip writing the .preview.svg/.png next to the compiled screen (for from-svg)",
        )
        p_visu.add_argument(
            "--no-png",
            action="store_true",
            help="Write only the preview SVG, do not rasterise (for preview)",
        )
        p_visu.add_argument(
            "--grid",
            type=int,
            default=0,
            help="Overlay a grid of this spacing on the preview, in px (for preview)",
        )
        p_visu.add_argument(
            "--fix",
            action="store_true",
            help="Rewrite the mechanically fixable findings in place (for lint)",
        )
        p_visu.add_argument(
            "--strict",
            action="store_true",
            help="Treat any lint finding as fatal (for lint, from-svg)",
        )




__all__ = ["register"]
