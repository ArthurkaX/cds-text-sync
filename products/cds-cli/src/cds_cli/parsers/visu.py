"""Argument registration for offline visualization commands."""

import argparse


def register(subparsers):
        # -- visu subcommand (offline) ------------------------------------------
        p_visu = subparsers.add_parser(
            "visu",
            help="Generate and manage CODESYS visualization XML files",
            description="Offline commands to create screens and add elements. "
            "These write .xml files directly into project-view/ "
            "for later import via ``cts import``.",
            epilog="""
    Two-phase workflow: draw, then wire signals. Do them as separate passes --
    do not lay out a whole screen and bind every variable in one sitting.

    PHASE 1 -- draw (geometry, style, gradients; no variables yet)
      1. scaffold a sketch (records canvas size + colour scheme):
           cts visu new --name Overview --w 1024 --h 768 \\
             --out overview.svg
      2. edit overview.svg -- add ONE or TWO elements, not the whole screen
      3. look at it before adding more:
           cts visu preview --svg overview.svg      # resolved SVG + PNG
           cts visu lint --svg overview.svg [--fix] # grid/type/overflow
      4. repeat 2-3 a few elements at a time until the layout is right
      5. compile into project-view/ as a NEW screen:
           cts visu from-svg --svg overview.svg --create-screen \\
             --screen-name Overview \\
             --folder "Runtime/PLC Logic/Application/HMI" \\
             --sync-folder <project>/project-view

    PHASE 2 -- wire signals (attach PLC variables, one element at a time)
      6. cts visu bind --svg overview.svg --elem 2 --var VisuVars.xRunning
         (bind only ever touches data-var/data-text-var/data-cds-tap/
         data-cds-action on the ONE flagged element -- it cannot move,
         resize, recolor or gradient anything, so it is safe to run
         between preview/lint checks without re-reviewing the layout)
      7. recompile in place, keeping the screen's Guid, and emit the GVL:
           cts visu from-svg --svg overview.svg --replace \\
             --screen Overview \\
             --folder "Runtime/PLC Logic/Application/HMI" \\
             --sync-folder <project>/project-view \\
             --gvl VisuVars
      8. repeat 6-7 per element, or batch several `bind` calls before one
         recompile -- `cts visu lint` already flags buttons/textfields/lamps
         left unbound, so run it again after phase 2 too
         NOTE: --replace takes --screen (the existing name); only
         --create-screen takes --screen-name. Mixing them silently
         creates a second screen instead of replacing.

      9. push it into the open CODESYS project:
           cts import          # add --save to persist, see cts import --help
      Everything up to step 7 is offline and safe to iterate on; only
      step 9 touches the IDE.

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

      Gradient fills (rect, circle, ellipse only):
        Declare a gradient in <defs> and reference it with fill="url(#id)":

          <defs>
            <linearGradient id="bar" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="#8FB6FF"/>
              <stop offset="100%" stop-color="#1B3A6B"/>
            </linearGradient>
            <radialGradient id="knob" cx="35%" cy="35%">
              <stop offset="0%"   stop-color="#F2F2F4"/>
              <stop offset="100%" stop-color="#6B6E75"/>
            </radialGradient>
          </defs>
          <rect x="20" y="20" width="200" height="60" fill="url(#bar)"/>
          <circle cx="300" cy="120" r="70" fill="url(#knob)"/>

        - CODESYS gradients hold exactly TWO colour stops. Only the first
          and last <stop> are used; any middle stop is silently dropped.
        - <linearGradient>: the angle comes from x1/y1 -> x2/y2 via atan2
          (0% 0% -> 100% 0% is 0 deg = left-to-right; ...-> 0% 100% is 90 deg
          = top-to-bottom). Centre is fixed at 50/50.
        - <radialGradient>: cx/cy become the gradient centre in percent
          (default 50/50). r is ignored -- CODESYS has no radius field.
        - stop-opacity is honoured and becomes the stop's alpha byte, which
          is exactly the Gradient Editor dialog's "Transparency 0-255" field
          (255 = opaque; the label says transparency but the value is
          opacity). Colours serialize as 0xAARRGGBB.
        - gradientUnits, gradientTransform, spreadMethod and xlink:href
          template inheritance are all ignored.
        - fill="url(#id)" replaces the solid fill; a shape has either a
          gradient or a flat fill, never both. An unresolvable url(#id)
          falls back to flat-fill parsing of the literal string.
        - CODESYS also has an "axial" gradient type, but SVG has no
          equivalent construct, so from-svg only ever emits linear/radial.
          Two stacked rects with mirrored linear gradients approximate it
          (reads as a chrome cylinder).

      Metal look, from a live-verified screen:
        - radial with cx/cy near 35%/35% and a light -> mid-dark stop pair
          reads as a polished sphere (rollers, knobs, lamps)
        - a vertical linear gradient reads as a brushed-metal plate
        - reversing a plate's stops (dark top, light bottom) reads as an
          engraved recess, which is how you sink a sub-panel into a console
        - keep live textfields on LIGHT insets: native controls ignore SVG
          colours and inherit the project style, so dark metal underneath
          them risks unreadable text

      Look before you import:
        cts visu preview --svg screen.svg        # resolved SVG + PNG
        cts visu lint --svg screen.svg [--fix]   # grid, type scale, overflow

      Unsupported in v1: polygon, polyline, image, transform,
        filters, masks, animation, viewBox scaling, multi-stop and
        text/line gradients,
        Table, ComboBox, TabControl, GroupBox, Checkbox, etc.

    bind (phase 2 -- wiring signals):
      cts visu bind --svg overview.svg --elem N [flags]
        --elem N        index of the element in the SVG, 0-based, in document
                         order (same numbering as the elements you wrote;
                         `cts visu lint` findings are indexed the same way)
        --var NAME       lamp / combobox / image-switcher: the bound variable
        --color ROLE     lamp: colour role, e.g. green|yellow|red
        --text-var NAME  textfield: the displayed/edited variable
        --tap NAME       button: TAP action -> data-cds-tap="tap:NAME"
        --toggle NAME    button: TOGGLE action -> data-cds-tap="toggle:NAME"
        --action TEXT    button/rectangle: raw data-cds-action clause, e.g.
                         'OnMouseClick: ST HMI.xReset := TRUE;' -- appended
                         with " || " if the element already has one
        --clear          remove every binding from the element instead

      Only one element is ever touched per call, and only its data-var /
      data-text-var / data-cds-tap / data-cds-action / data-color attributes
      -- geometry, fill, stroke and gradients are untouched. Passing a flag
      the element type doesn't support (e.g. --tap on a lamp) is refused.
      Hand-editing these same attributes directly in the SVG remains valid;
      `bind` exists so getting a variable onto the right element does not
      require re-reading the whole SVG contract above.
    """,
        )
        p_visu.formatter_class = argparse.RawDescriptionHelpFormatter
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
                "bind",
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
            "bind - attach/clear one PLC variable binding on an SVG element\n"
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
            "--elem", type=int, help="Element index (for describe --screen --elem, bind)"
        )
        p_visu.add_argument(
            "--var", default=None, help="Bind variable, e.g. VisuVars.xRunning (for bind: lamp/combobox/image-switcher)"
        )
        p_visu.add_argument(
            "--text-var", default=None, help="Bind display variable (for bind: textfield)"
        )
        p_visu.add_argument(
            "--tap", default=None, help="Bind tap variable (for bind: button)"
        )
        p_visu.add_argument(
            "--toggle", default=None, help="Bind toggle variable (for bind: button)"
        )
        p_visu.add_argument(
            "--color", default=None, help="Lamp colour role: green|yellow|red|... (for bind: lamp)"
        )
        p_visu.add_argument(
            "--action",
            default=None,
            help='Raw data-cds-action clause, e.g. "OnMouseClick: ST HMI.Var := TRUE;" (for bind: button/rectangle)',
        )
        p_visu.add_argument(
            "--clear",
            action="store_true",
            help="Remove every binding from the element instead of setting one (for bind)",
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
