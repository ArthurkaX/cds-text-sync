---
name: codesys-visu
description: Author, draw, validate, and import CODESYS visualization screens using the `cts visu` command group. Supports rectangle/ellipse/rounded-rectangle/line elements via the VisuFbElemSimple catalog type. New element types can be added by placing a JSON file in the catalog -- no code changes.
disable-model-invocation: true
---

# Author CODESYS Visualizations with `cts visu`

This skill teaches an AI agent to use the `cts visu` command group (part of the
`cds-text-sync` toolkit at `C:\Workspace\Active\cds-text-sync`) to create and
modify CODESYS visualization screens. The tool generates offline `.xml` files
in a project-view directory, ready for import via `cts import`.

For element types NOT yet covered by `cts visu` (see coverage below), the
`references/` directory holds verified ground-truth documentation for
hand-authoring XML using the IArchivable serialization format. But the primary
path is always `cts visu` for supported types.

## Prerequisites

- `cds-text-sync` installed and `cts` on PATH (or run via `python -m cli.cds_text_sync`)
- Daemon connected to a CODESYS project (run `cts connect` first)
- The PLC must be **offline** for `cts import` to succeed
- A `project-view/` directory on disk (the `cts` toolchain writes there)

## Step-by-step workflow

### 1. Discover available element types

```
cts visu types
```

This lists every type in the catalog. Currently one type: `rectangle`
(`VisuFbElemSimple` for basic shapes).

### 2. Learn a type's properties

```
cts visu describe --type rectangle
```

Prints shape variants, settable properties with defaults, optional variable
bindings, and validation invariants. Example output:

```
Type: rectangle  (VisualElementTypeName=VisuFbElemSimple)

Shape variants:
  ellipse      -> VISU_ST_CIRCLE
  line         -> VISU_ST_LINE
  rectangle    -> VISU_ST_RECTANGLE
  rounded      -> VISU_ST_ROUNDED_RECTANGLE

Settable properties:
  alarm_fill      kind=color    default='-12337'   Alarm fill color
  alarm_frame     kind=color    default='-65536'   Alarm frame color
  alarm_text      kind=color    default='-16777216' Alarm text color
  angle           kind=int      default='0'         Rotation angle (degrees)
  border_width    kind=uint     default='1'         Border/line width, usually 1
  corner_radius   kind=short    default='5'         Corner radius (rounded)
  fill            kind=color    default='-1'        Fill color
  font_name       kind=string   default='Arial'     Font name
  font_size       kind=short    default='12'        Font size
  frame           kind=color    default='-16777216' Frame/border color
  h_align         kind=string   default='HCENTER'   Horizontal align
  height          kind=int      default='100'       Height, px [geometry]
  shape           kind=shape    default='VISU_ST_RECTANGLE'  Shape variant: rectangle|ellipse|rounded|line
  text            kind=string   default=''          Static text [requires=textid]
  tooltip         kind=string   default=''          Tooltip text
  v_align         kind=string   default='VCENTER'   Vertical align
  width           kind=int      default='100'       Width, px [geometry]
  x               kind=int      default='0'         X (left) [geometry]
  y               kind=int      default='0'         Y (top) [geometry]
```

Colors are accepted as `0xAARRGGBB` hex, `#AARRGGBB`, or `AARRGGBB`.

### 3. Create a new screen

```
cts visu create-screen \
    --name MyScreen \
    --folder "Runtime/PLC Logic/Application/HMI" \
    --width 800 \
    --height 480 \
    --start-visu
```

Generates a `<name>.xml` file in the target folder within project-view.

**Placement rule:** The tool copies `ParentGuid` / `ParentSVNodeGuid` from an
existing sibling object in the target folder. Therefore the folder MUST already
contain at least one visu/object file (a brand-new empty folder will fail with
a clear error).

### 4. Add elements

```
cts visu add --screen MyScreen --type rectangle \
    --x 10 --y 10 --w 200 --h 100 \
    --shape rounded --corner-radius 8 \
    --fill 0xFFCC0000 --frame 0xFF000000 --border-width 2 \
    --tooltip "Click to start"
```

Each `add` call appends one element. The `--shape` flag selects the variant:
`rectangle`, `ellipse`, `rounded`, or `line`. Geometry is bounds-checked
against the screen canvas at add time (X>=0, Y>=0, X+W <= SizeX, Y+H <= SizeY).
CenterX and CenterY are auto-computed as `X + W//2` and `Y + H//2`.

Available `--type` values are the keys printed by `cts visu types`.

`--screen` resolves by name (recursive search under project-view) or by path;
`--folder` is optional when the name is unambiguous.

Repeat for each element.

### 5. List elements on a screen

```
cts visu list --screen MyScreen
```

Prints a table of index, type, identifier, X, Y, W, H.

### 6. Validate the screen

```
cts visu check --screen MyScreen
```

Checks:
- Every element is within canvas bounds
- No element overlap
- CenterX/CenterY match `X + W/2`
- Every color struct has a non-empty `CanonicalName`
- If `text` member is non-empty, a Text ID member (823443203) is present

### 7. Import into CODESYS

```
cts import
```

Uploads the generated XML files into the connected CODESYS project. The PLC
must be offline.

### 8. (Optional) Build to confirm

```
cts build
```

Useful for catching CODESYS compile errors. Wait for the build to complete and
check for 0 errors.

## Invariants

These are enforced by `cts visu check` and must never be violated:

1. **Canvas bounds** -- every element's X>=0, Y>=0, X+W <= SizeX, Y+H <= SizeY.
2. **CanonicalName non-empty** -- every color struct must have a non-empty
   `CanonicalName` string. Empty crashes the CODESYS codegen at build time
   (`StylesNamedObjectsHelper.GetNamedObjectIdentifierExpr` asserts
   `!string.IsNullOrEmpty(name)`).
3. **Text requires Text ID** -- if an element's text member (390574330) is
   non-empty, a Text ID member (823443203) is REQUIRED. CODESYS rejects the
   import with *"One of the identified items was in an invalid format"* if this
   is missing. **Currently `cts visu` blocks --text to prevent this error**;
   the feature is not yet supported. Omit `--text` for now.

## Coverage / growth model

Only element types with a JSON catalog file under `cli/visu/catalog/` are
supported by `cts visu`. Currently only `rectangle` is present, covering the
`VisuFbElemSimple` element (rectangle, ellipse, rounded-rectangle, line).

**To add a new type** (no Python code changes needed):
1. Export a real element from the CODESYS IDE as `.xml`
2. Create `cli/visu/catalog/<name>.json` following the schema in
   `cli/visu/DESIGN.md`
3. The engine picks it up automatically -- `cts visu types` will list it

This means the catalog is extensible by any developer who can capture ground
truth from CODESYS.

## When `cts visu` doesn't cover it

For element types not yet in the catalog (buttons, textfields, lamps, alarms,
tables, sliders, etc.), or when you need custom XML such as input actions,
containers (frames/groups/tables), or nested elements:

- Use `references/` for the full reference documentation
- Start from a matching `examples/*.xml` as structural template
- Check the format guidelines in `references/format-overview.md`
- Verify property IDs in `references/property-ids.md`
- Follow color/font encoding in `references/colors-and-fonts.md`

The reference docs are migrated from the original CODESYS visu skill --
they document the full IArchivable XML serialization format, NOT the `cts visu`
tool API.
