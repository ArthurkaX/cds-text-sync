---
name: cds-visu-svg
description: Generate SVG sketches for CODESYS visualization, conforming to the
  `cts visu from-svg` schema. Use when the user wants to create,
  modify, or debug SVG files that compile into CODESYS HMI screens.
  disable-model-invocation: true
---

# cds-visu-svg — SVG → CODESYS visu transpiler

The user has `cts visu from-svg` which compiles an SVG file directly into a
CODESYS visualization `.xml` file. Your job is to generate **valid SVG** that
this tool can consume, ask the user to review/approve it, then compile it to a
CODESYS visualization object using `cts visu from-svg` only after approval.

## Workflow

1. **Ask for the CODESYS visual style first** unless the user already named one.
   Offer available style names from `cli/visu/themes` / `cts visu from-svg
   --theme` vocabulary when known. Prefer `flat-style` as the default only if
   the user does not choose. Do not invent editor-like themes.
2. **Generate the SVG** according to the rules below and write it to the project
   at the path the user requested (or a sensible default named after the screen,
   e.g. `<screen>.svg`).
3. **Generate the GVL automatically** (see "GVL variable declarations"
   section below). When compiling, use the `--gvl` flag to auto-generate
   declarations for all runtime variables detected in the SVG:
   ```sh
   cts visu from-svg <screen>.svg --screen <ScreenName> --gvl VisuVars
   ```
   For a custom output path use:
   ```sh
   cts visu from-svg <screen>.svg --screen <ScreenName> --gvl-file path/to/GVL_HMI.st
   ```
   This is **recommended** for every SVG that uses `data-text-var`,
   `data-cds-tap`, or `data-cds-action`. Variables already declared in
   existing GVL files are silently skipped.
4. **Pause for visual approval.** Tell the user the SVG path and invite them to
   open/review it. Do not run `cts visu from-svg` yet unless the user already
   explicitly requested an unattended compile in the same request. If browser or
   image-preview tooling is available, offer or use it to show the SVG preview.
5. **After the user approves, compile it.** If `cts` is available in the
   environment, run:
   ```sh
   cts visu from-svg <path-to-svg> --screen <ScreenName> --gvl VisuVars
   ```
   Use the appropriate ``--theme`` (default: ``flat-style``) and ``--folder``
   for the target folder in the CODESYS project tree. Include ``--gvl`` to
   auto-generate variable declarations when the SVG uses runtime bindings.
6. If `cts` is **not** available, report this clearly and provide the exact
   command the user can run manually.
7. Always report the compile result (success / error / waiting for approval /
   not run).

### Approval rule

Treat SVG generation and CODESYS XML import as two separate steps. A normal
visualization request should stop after the `.svg` is written and reviewed.
Proceed to `from-svg` only after the user says to continue, approves the SVG, or
explicitly asks for immediate compilation.

## Canvas

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480" viewBox="0 0 800 480">
  <defs><style>:root{ --surface:#161B22; --primary:#58A6FF; --frame:#30363D; }</style></defs>
  ...
</svg>
```

- `width` / `height` → screen size. `viewBox` must be `0 0 <width> <height>`.
- Coordinate system: top-left origin, y-down, 1 user-unit = 1 px.
- The screen background is set from theme `--surface`. Set `--surface` in `:root`
  and the transpiler automatically applies it (BgColor=True + BgUseColor).
  If no `--surface` is set, the default CODESYS white background is used.
- **Always** include a `<defs><style>:root{ … }</style></defs>` block with the
  theme roles you use. This makes the SVG preview correctly in any browser and
  supplies fallback values to the transpiler.

## Theme CSS variables (`:root` block)

```css
:root{
  --surface:#…;       /* screen background */
  --panel:#…;         /* grouping panel / custom container fill */
  --custom-fill:#…;   /* custom primitive default fill */
  --custom-frame:#…;  /* custom primitive default border */
  --divider:#…;       /* separator lines */
  --primary:#…;       /* accent / main action colour */
  --frame:#…;         /* legacy border / stroke colour */
  --text:#…;      /* font colour */
}
```

Recommended layout/custom roles: `surface`, `screen.background`, `panel`,
`panel.frame`, `panel.header`, `panel.header.text`, `custom.fill`,
`custom.frame`, `custom.text`, `custom.accent.fill`, `custom.accent.text`,
`divider`, `focus`.

Status/accent roles: `primary`, `secondary`, `accent`, `element.active`,
`success`, `warning`, `error`, `muted`, `text`, `text.muted`, `on-surface`.

## Element vocabulary

| SVG | CODESYS element | Attributes consumed |
|---|---|---|
| `<rect>` | `VisuFbElemSimple` (rectangle) | `x y width height` `fill stroke stroke-width` |
| `<rect rx="…">` | `VisuFbElemSimple` (rounded) | same as rect + `rx` |
| `<circle>` | `VisuFbElemSimple` (ellipse) | `cx cy r` `fill stroke stroke-width` |
| `<ellipse>` | `VisuFbElemSimple` (ellipse) | `cx cy rx ry` `fill stroke stroke-width` |
| `<line>` | `VisuFbElemLine` | `x1 y1 x2 y2` `stroke stroke-width` |
| `<text>` | `VisuFbLabel` | `x y` `fill` (font colour) `font-size font-family` + textContent |
| `<rect data-cds-type="button">` | `VisuFbElemButton` | geometry + `data-text` (caption) |
| `<text data-cds-type="textfield">` | `VisuFbElemTextfield` | `x y` `data-width data-height` `data-text-var` + textContent |

## Color rules

- Use `fill="var(--role)"` or `stroke="var(--role)"` — the transpiler resolves
  `var(--role)` to a literal ARGB uint so the element gets a real colour and
  does **not** depend on the visual style (no "white elements").
- Native CODESYS controls such as `data-cds-type="button"` should usually omit
  `fill` and `stroke`; CODESYS applies the selected visual style itself. Use
  themed custom rectangles around those controls for panels, grouping and
  emphasis.
- Use literal hex `#RRGGBB` / `#RRGGBBAA` when you want a specific colour.
- `<text fill="...">` controls **font colour**.
- **Background colour** is controlled by `--surface` in `:root`.
  You do NOT need a separate rect for it.
- **Textfields** use `fill` as their font colour.
- **Native buttons** may still be affected by the project visual style. For
  predictable coloured button-like visuals, use a plain `<rect>` plus `<text>`.

## Data attributes for controls

### Button
```xml
<rect x="100" y="200" width="120" height="40"
      data-cds-type="button" data-text="Start" />
```
- `data-text` — button caption. The transpiler allocates a Text-ID in the
  GlobalTextList automatically.
- `data-cds-tap="TAP HMI.StartPump"` — bind the native CODESYS button
  tap/toggle variable.
- `data-cds-action` — optional native action binding. Supported forms:
  `TAP HMI.StartPump`, `TOGGLE HMI.StartPump`,
  `OnMouseClick: ST HMI.StartPump := TRUE;`,
  `OnMouseDown: toggle HMI.StartPump`, and
  `OnMouseUp: screen CoolingTower`. Separate multiple actions with `||`.

### Textfield (runtime variable display)
```xml
<text x="300" y="50" font-size="16" font-family="Arial"
      data-cds-type="textfield" data-width="200" data-height="30"
      data-text-var="HMI.Temperature">show %3.2f</text>
```
- `data-width` / `data-height` — bounding box (required; `<text>` has no
  native width/height).
- `data-text-var` — optional runtime variable binding (e.g. `HMI.MyVar`).
- Text content — the display format string.
- `fill="..."` — textfield font colour (optional, otherwise inherits style).

## GVL variable declarations (auto-generated)

Every variable referenced by a control element **must** have a corresponding
declaration in a GVL (Global Variable List) `.st` file. The transpiler can
**auto-generate** these when you pass the `--gvl` flag:

```sh
cts visu from-svg <screen>.svg --screen <ScreenName> --gvl VisuVars
```

Auto-detected sources:
- `data-text-var="HMI.MyVar"` → `MyVar` declared in the GVL
- `data-cds-tap="TAP HMI.StartPump"` → `StartPump` declared in the GVL
- `data-cds-action="..."` → variables extracted from action bindings

Variables that already exist in the project's GVL files are skipped.
If no runtime variables are detected, the GVL file is not created.

If you prefer to create the GVL manually, see the convention below.

### Convention

- Use `GVL_HMI.st` as the default GVL name for HMI-scope variables.
  Place it under the application folder:
  ```
  project-view/Runtime/PLC Logic/Application/GVL_HMI.st
  ```
- If a GVL with a specific name already exists in the project (e.g.
  `GVL_Routing`, `GVL_Sensors`), reuse it and add your HMI variables there
  rather than creating a duplicate.

### Format

```iecst
{attribute 'qualified_only'}
VAR_GLOBAL
	// HMI visualization variables
	MyVariable : BOOL := FALSE;
	MyCounter  : INT  := 0;
	MyValue    : REAL := 0.0;
END_VAR
```

- Begin with `{attribute 'qualified_only'}` to prevent name collisions.
- Use `VAR_GLOBAL` / `END_VAR` block.
- Declare each HMI variable with its correct type and an initial value.
- Add a brief comment describing the variable's purpose.

### What must be declared

| Source | Attribute | Variable path example | Required GVL declaration |
|--------|-----------|----------------------|--------------------------|
| Textfield `data-text-var` | `data-text-var="HMI.Temperature"` | `HMI.Temperature` | `Temperature : REAL;` inside GVL named `HMI` or directly in `GVL_HMI` |
| Button `data-cds-tap` action | `data-cds-tap="TAP HMI.StartPump"` | `HMI.StartPump` | `StartPump : BOOL;` inside GVL named `HMI` or directly in `GVL_HMI` |
| Textfield `data-text-var` (structured) | `data-text-var="GVL_Sensors.Scale.Q"` | `GVL_Sensors.Scale.Q` | Already declared in `GVL_Sensors` — no new declaration needed (reference existing) |

### Rules

1. **Collect all unique variable paths** from every control in the SVG.
2. **Normalise** the paths: if a path starts with a known GVL name (e.g.
   `GVL_Sensors.`), verify that GVL already contains the declaration. If it
   does not, add it to that GVL.
3. **For flat `HMI.*` paths**, create or update the `GVL_HMI.st` file with
   all variables as members of a single `VAR_GLOBAL` block.
4. **Do not duplicate** existing declarations. Check the project's existing
   GVL files first before creating new ones.
5. **Report** which GVL file was created/updated in your workflow summary.

### Example — GVL_HMI.st for the Pump Station sketch

```iecst
{attribute 'qualified_only'}
VAR_GLOBAL
	// HMI visualization variables for Pump Station screen
	StartPump    : BOOL := FALSE;
	StopPump     : BOOL := FALSE;
	Temperature  : REAL := 0.0;
	MotorRunning : BOOL := FALSE;
	MotorSpeed   : INT  := 0;
END_VAR
```

## Text & Text-IDs

The transpiler **automatically** allocates Text-IDs for any element with
non-empty text and writes the entry to the project's `GlobalTextList`. You
do **not** need to specify a Text-ID yourself.

## Actions

You may add `data-cds-tap` for simple native button tap bindings:

```xml
<rect data-cds-type="button" data-text="Stop" data-cds-tap="TAP HMI.StopPump" .../>
```

Use `data-cds-action` for broader button actions:

```xml
<rect data-cds-type="button" data-text="Toggle"
      data-cds-action="TOGGLE HMI.StartPump" .../>
<rect data-cds-type="button" data-text="Start"
      data-cds-action="OnMouseClick: ST HMI.StartPump := TRUE;" .../>
<rect data-cds-type="button" data-text="Next"
      data-cds-action="OnMouseClick: screen CoolingTower" .../>
```

Compiled forms:
- `TAP <variable>` -> CODESYS `Visu_TapInput`
- `TOGGLE <variable>` -> CODESYS `Visu_ToggleInput`
- `OnMouseClick/OnMouseDown/OnMouseUp: ST <snippet>` -> `STSnippet`
- `OnMouseClick/OnMouseDown/OnMouseUp: toggle <variable>` -> `ToggleVariable`
- `OnMouseClick/OnMouseDown/OnMouseUp: screen <screen>` -> change screen assignment

Hotkeys are not generated yet; the observed CODESYS XML stores them at screen
level under `Hotkeys`, not inside the button element.

## Unsupported (will raise a clear error)

- `<polygon>`, `<polyline>`, `<image>`
- `transform`, nested `<svg>`, `viewBox` scaling, gradients, filters, masks,
  CSS classes, animation
- Table, ComboBox, TabControl, GroupBox, Checkbox, RadioButton, Slider,
  Scrollbar, SpinControl, ProgressBar, InvisibleInput

## Example — Pump Station sketch

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480" viewBox="0 0 800 480">
  <defs><style>:root{
    --surface:#1e1e1e; --primary:#0078d4; --on-surface:#ffffff;
    --frame:#555555; --success:#4caf50; --warning:#ff9800;
  }</style></defs>

  <text x="20" y="36" fill="var(--on-surface)" font-size="20" font-family="Arial">Pump Station 1</text>
  <line x1="20" y1="50" x2="780" y2="50" stroke="var(--frame)" stroke-width="1"/>

  <rect x="20" y="70" width="360" height="160" fill="var(--panel)" stroke="var(--panel-frame)" stroke-width="2" rx="8"/>
  <text x="30" y="100" fill="var(--on-surface)" font-size="14" font-family="Arial">Motor: Running</text>
  <text x="30" y="130" fill="#888888" font-size="12" font-family="Arial">Speed: 1450 RPM</text>

  <circle cx="330" cy="100" r="20" fill="var(--success)"/>

  <rect x="20" y="250" width="340" height="70" fill="var(--panel)" stroke="var(--panel-frame)" stroke-width="1" rx="4"/>
  <rect x="30" y="265" width="140" height="40"
        data-cds-type="button" data-text="Start Pump"/>
  <rect x="190" y="265" width="140" height="40"
        data-cds-type="button" data-text="Stop Pump"/>

  <text x="20" y="260" font-size="14" font-family="Arial"
        data-cds-type="textfield" data-width="200" data-height="30"
        data-text-var="HMI.Temperature" fill="var(--warning)">%3.1f C</text>

  <line x1="20" y1="340" x2="780" y2="340" stroke="var(--divider)" stroke-width="1"/>

  <text x="20" y="420" fill="var(--on-surface)" font-size="14" font-family="Arial">Alarms</text>
  <rect x="20" y="435" width="180" height="30" fill="var(--surface)" stroke="var(--success)" stroke-width="1"/>
  <text x="28" y="454" fill="var(--success)" font-size="11" font-family="Arial">Level Sensor OK</text>
  <rect x="210" y="435" width="180" height="30" fill="var(--surface)" stroke="var(--warning)" stroke-width="1"/>
  <text x="218" y="454" fill="var(--warning)" font-size="11" font-family="Arial">Temp High Warning</text>
</svg>
```
