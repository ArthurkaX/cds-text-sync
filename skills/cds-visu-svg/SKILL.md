---
name: cds-visu-svg
description: >-
  Generate SVG sketches for CODESYS visualization, conforming to the
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

1. **Scaffold a starter SVG** with `cts visu new`. This writes a valid,
   ready-to-edit sketch that already contains one EXAMPLE of every common
   element and a commented list of the colour classes — always start from it
   instead of writing an SVG from a blank canvas:
   ```sh
   cts visu new --name "<Screen>" --w 800 --h 480 --out <screen>.svg
   ```
2. **Edit the SVG**: keep or adjust the example elements, add more as needed.
   Colour comes from `class="..."` (see "Colour classes" below) — you do not
   write colours yourself. For elements beyond the seed, copy from the files in
   the skill's `examples/` folder (`status-panel.svg`, `pid-schematic.svg`).
   The screen background is set for you; never add a full-screen background rect.
3. **Generate the GVL automatically** (see "GVL variable declarations"
   section below). When compiling, use the `--gvl` flag to auto-generate
   declarations for all runtime variables detected in the SVG:
   ```sh
   cts visu from-svg --svg <screen>.svg --screen <ScreenName> --gvl VisuVars
   ```
   For a custom output path use:
   ```sh
   cts visu from-svg --svg <screen>.svg --screen <ScreenName> --gvl-file path/to/GVL_HMI.st
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
   cts visu from-svg --svg <screen>.svg --create-screen --screen-name <ScreenName> \
     --folder "Runtime/PLC Logic/Application/HMI" --gvl VisuVars
   ```
   - **First compile:** use `--create-screen --screen-name <ScreenName> --folder "<CODESYS folder>"` to create the screen.
   - **Recompiling an existing screen:** use `--screen <ScreenName> --folder "<CODESYS folder>"` instead (do NOT pass `--create-screen` again — it errors "Screen already exists").
   - `--folder` selects the location in the CODESYS project tree (e.g. `Runtime/PLC Logic/Application/HMI`).

   Use the appropriate ``--theme`` (default: ``flat-style``). Include ``--gvl`` to
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
<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">
  ...
</svg>
```

- `width` / `height` → screen size.
- Coordinate system: top-left origin, y-down, 1 user-unit = 1 px.
- The screen **background is set automatically** (from the CODESYS style /
  `--theme`). Do NOT add a full-screen `<rect>` to paint the background, and do
  NOT add a `<defs>`/`<style>` block — colour is chosen by class, not inline.

## Colour classes

You never write a colour. Put a **class** on an element and the active CODESYS
style / theme decides the actual colour. This means an element always gets a
real colour that matches the project style — no "white elements", and the same
sketch re-themes automatically.

| class | use on | meaning |
|---|---|---|
| `panel` | `<rect>` | grouping / container backing |
| `card` | `<rect>` | lighter inner surface |
| `title` | `<text>` | heading text |
| `value` | `<text>` | large read-out number / text |
| `divider` | `<line>` | separator line |
| `ok` | `<rect>` | status: healthy / running |
| `warn` | `<rect>` | status: caution |
| `alarm` | `<rect>` | status: fault (fill + frame) |
| `pipe-water` | `<line>` `<rect>` `<ellipse>` | P and ID fluid line / vessel |
| `metal` | `<rect>` `<circle>` `<ellipse>` | P and ID structural / equipment |

- **Buttons and textfields take NO class.** They inherit the native CODESYS
  control style automatically — leave their colour alone.
- Classes are defined in `cli/visu/stylesheet.css` and can be extended, or
  overridden per project with a `visu.css` in the project-view directory. To add
  a new colour meaning, add a class there rather than hard-coding a colour.
- Escape hatch (rare): an explicit `fill="#RRGGBB"` / `stroke="#RRGGBB"` still
  works and overrides the class, but prefer a class so the screen stays themed.

## Element vocabulary

| SVG | CODESYS element | Attributes consumed |
|---|---|---|
| `<rect>` | `VisuFbElemSimple` (rectangle) | `x y width height` `class` |
| `<rect rx="…">` | `VisuFbElemSimple` (rounded) | same as rect + `rx` |
| `<circle>` | `VisuFbElemSimple` (ellipse) | `cx cy r` `class` |
| `<ellipse>` | `VisuFbElemSimple` (ellipse) | `cx cy rx ry` `class` |
| `<line>` | `VisuFbElemLine` | `x1 y1 x2 y2` `class` |
| `<text>` | `VisuFbLabel` | `x y` `class` `font-size font-family` + textContent |
| `<rect data-cds-type="button">` | `VisuFbElemButton` | geometry + `data-text` (caption) |
| `<text data-cds-type="textfield">` | `VisuFbElemTextfield` | `x y` `data-width data-height` `data-text-var` + textContent |

## Advanced elements (lamp, image-switcher, combobox, alarm-banner)

These specialized native controls are documented separately in
`reference/advanced-elements.md`. **Do not read that file unless the user
specifically asks for one of these controls** — the core elements above cover
almost every screen. When you do need one, read only that file's section for
the control in question.

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
- Font colour comes from the CODESYS style; add a class only if you need a
  specific themed colour (e.g. `class="value"`).

## GVL variable declarations (auto-generated)

Every variable referenced by a control element **must** have a corresponding
declaration in a GVL (Global Variable List) `.st` file. The transpiler can
**auto-generate** these when you pass the `--gvl` flag:

```sh
cts visu from-svg --svg <screen>.svg --screen <ScreenName> --gvl VisuVars
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
  animation
- Inline `<style>` / `:root` theme blocks (colour comes from `class`, not CSS
  variables). Only the `class` names listed in "Colour classes" are recognised.
- Table, TabControl, GroupBox, Checkbox, RadioButton, Slider,
  Scrollbar, SpinControl, ProgressBar, InvisibleInput

## Example — Pump Station sketch

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">

  <text class="title" x="20" y="36">Pump Station 1</text>
  <line class="divider" x1="20" y1="50" x2="780" y2="50"/>

  <rect class="panel" x="20" y="70" width="360" height="160" rx="8"/>
  <text x="30" y="100" font-size="14">Motor: Running</text>
  <circle class="ok" cx="330" cy="100" r="20"/>

  <rect class="panel" x="20" y="250" width="340" height="70" rx="4"/>
  <rect x="30" y="265" width="140" height="40"
        data-cds-type="button" data-text="Start Pump"
        data-cds-tap="TAP HMI.StartPump"/>
  <rect x="190" y="265" width="140" height="40"
        data-cds-type="button" data-text="Stop Pump"
        data-cds-tap="TAP HMI.StopPump"/>

  <text class="value" x="400" y="120"
        data-cds-type="textfield" data-width="200" data-height="30"
        data-text-var="HMI.Temperature">%3.1f C</text>

  <line class="divider" x1="20" y1="340" x2="780" y2="340"/>

  <text class="title" x="20" y="420">Alarms</text>
  <rect class="ok" x="20" y="435" width="180" height="30"/>
  <text x="28" y="454" font-size="11">Level Sensor OK</text>
  <rect class="warn" x="210" y="435" width="180" height="30"/>
  <text x="218" y="454" font-size="11">Temp High Warning</text>
</svg>
```
