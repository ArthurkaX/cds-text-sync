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

1. **Scaffold a starter SVG** with `cts visu new`. This composes a complete,
   already-laid-out screen for the canvas size you ask for — header band,
   content panel, KPI cards, a bound field, a status row, an action row — plus a
   commented list of the colour classes. Always start from it instead of writing
   an SVG from a blank canvas:
   ```sh
   cts visu new --name "<Screen>" --w 800 --h 480 --out <screen>.svg
   ```
2. **Edit the SVG**: keep or adjust the example elements, add more as needed.
   Colour comes from `class="..."` (see "Colour classes" below) — you do not
   write colours yourself. Follow "Layout rules" below; the skeleton already
   does. For elements beyond the skeleton, copy from the files in the skill's
   `examples/` folder (`status-panel.svg`, `pid-schematic.svg`) — both of them
   lint clean, so they are safe to imitate.
   The screen background is set for you; never add a full-screen background rect.
3. **Check the design** with `cts visu lint`. It reports the things that make a
   technically valid screen look unfinished — off-grid coordinates, text wider
   than its box, a font size outside the scale, a button too small to press, a
   field with nothing bound to it:
   ```sh
   cts visu lint --svg <screen>.svg          # report
   cts visu lint --svg <screen>.svg --fix    # snap the mechanical ones
   ```
   Fix everything it reports before moving on. `--fix` rewrites only the
   attributes it flagged, leaving your comments and formatting intact; anything
   it cannot fix mechanically is a judgement call and is yours to make.
4. **Look at what you made.** The sketch itself carries no colours, so opening
   it in a viewer shows black shapes on white and tells you nothing. Render it
   with the real resolved palette and *actually open the PNG*:
   ```sh
   cts visu preview --svg <screen>.svg
   ```
   This writes `<screen>.preview.svg` and `<screen>.preview.png` next to the
   sketch. Read the PNG. Check the things lint cannot: is the hierarchy
   readable, is anything visually lost, does it look like a screen someone
   designed. Iterate here — this loop is cheap, the CODESYS round-trip is not.
5. **Generate the GVL automatically** (see "GVL variable declarations"
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
6. **Pause for visual approval.** Show the user the preview PNG from step 4 and
   tell them the SVG path. Do not run `cts visu from-svg` yet unless the user
   already explicitly requested an unattended compile in the same request.
7. **After the user approves, compile it.** If `cts` is available in the
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
   `from-svg` runs lint and preview itself; `--strict` makes lint findings fatal,
   `--no-preview` skips the PNG.
8. If `cts` is **not** available, report this clearly and provide the exact
   command the user can run manually.
9. Always report the compile result (success / error / waiting for approval /
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
  `--theme`). Do NOT add a full-screen `<rect>` to paint the background.
  `--background style|auto|#RRGGBB` on `from-svg` overrides it if you must.

## Layout rules

A screen that follows these looks designed; one that ignores them looks
generated. `cts visu lint` grades against them, so following them is also the
fastest way to a clean run.

- **4px grid.** Every `x`/`y`/`width`/`height` is a multiple of 4. Lay blocks
  out on 8 or 16 — the grid is the floor, not the rhythm.
- **24px page margin.** Nothing but the background touches the outer 24px.
- **16px between blocks, 16px panel padding.** Content starts 16px inside a
  `.panel`, and panels sit 16px apart.
- **Bands, not scatter.** Header (title + a divider at y≈72), body, then an
  action row above the bottom margin with a divider over it. Buttons live in the
  action row, not floating in the body.
- **One `.h1` per screen.** `.h2` per section, `.label` for body text,
  `.caption` for units and notes, `.value` for the one number that matters.
  Never write a bare `font-size` — pick a class.
- **Touch targets.** A button is at least 48×32; 160×48 is the comfortable
  default. A lamp is at least 16×16.
- **Text is anchored on its BASELINE.** This is the single most common mistake.
  For a `<text>` — including a `data-cds-type="textfield"` — the `y` you write is
  the baseline, and the compiled box top is `y - font-size`. So a 12px field
  whose box should start at 160 is written `y="172"`. With
  `text-anchor="middle"` the box is centred on `y` instead, so give it an
  explicit `data-height` or the centre lands off-grid.
- **24px from a label's baseline to its field's baseline.** That leaves 16px
  between the field and the next label.
- **Pipes are thin rects, not lines.** A CODESYS line has no width member, so
  `<line>` always draws one pixel wide — fine for a `.divider`, invisible for a
  process line. Draw a pipe as an 8px-tall `<rect class="pipe-water">`.

## Colour classes

You never write a colour. Put a **class** on an element and the active CODESYS
style / theme decides the actual colour. This means an element always gets a
real colour that matches the project style — no "white elements", and the same
sketch re-themes automatically.

| class | use on | meaning |
|---|---|---|
| `panel` | `<rect>` | grouping / container backing |
| `card` | `<rect>` | lighter inner surface, one step down |
| `divider` | `<line>` | separator line |
| `h1` | `<text>` | screen title (22px) — one per screen |
| `h2` | `<text>` | section / panel heading (16px) |
| `value` | `<text>` | large read-out (28px) |
| `label` | `<text>` | body text, field name (12px) |
| `caption` | `<text>` | units, secondary note (11px) |
| `muted` | `<text>` | de-emphasised, keeps its size |
| `inverse` | `<text>` | text sitting on a status / accent fill |
| `ok` | `<rect>` `<circle>` | status: healthy / running |
| `warn` | `<rect>` `<circle>` | status: caution |
| `alarm` | `<rect>` `<circle>` | status: fault (fill + frame) |
| `pipe-water` | `<rect>` `<line>` `<ellipse>` | P and ID fluid line / vessel |
| `metal` | `<rect>` `<circle>` `<ellipse>` | P and ID structural / equipment |

`title` still works as a legacy alias of `h1`; prefer `h1` in new sketches.

- **Buttons, textfields and lamps take NO class.** They inherit the native
  CODESYS control style automatically — leave their colour alone.
- Classes are defined in `cli/visu/stylesheet.css` and can be extended, or
  overridden per project with a `visu.css` in the project-view directory. To add
  a new colour meaning, add a class there rather than hard-coding a colour.
- Escape hatch (rare): an explicit `fill="#RRGGBB"` / `stroke="#RRGGBB"` still
  works and overrides the class, but prefer a class so the screen stays themed.
  An inline `<defs><style>:root { --water: #… }</style></defs>` block also works
  and overrides the theme for that one sketch — reach for it only when a screen
  genuinely needs a palette the project style does not have.

## Dark screens

A night shift reads the same screen in a dark control room. Ask for it once, at
scaffold time:

```sh
cts visu new --name "<Screen>" --w 800 --h 480 --scheme dark --out <screen>.svg
```

That records `data-cds-scheme="dark"` on the root `<svg>`, and **nothing else in
your workflow changes**. You still never write a colour: the same classes resolve
to the dark palette, so lint, preview and `from-svg` all follow the sketch
without being told. `--scheme dark|light` is also accepted by `lint`, `preview`
and `from-svg` if you want to see one sketch both ways — it overrides the
attribute for that single run, without editing the file.

Two things to know:

- **Lamps keep their indicator colours.** Red stays red on a dark screen. An
  indicator that changed meaning with the colour scheme would be a safety
  problem, so lamps are deliberately outside the palette.
- **In dark the palette is authoritative.** Every CODESYS visual style that
  ships is a light style, so on a dark screen the palette owns the surfaces,
  the text on them, and the button/textfield colours — `--theme` no longer
  changes those. Light is unchanged: it still defers to the project style.

## Element vocabulary

| SVG | CODESYS element | Attributes consumed |
|---|---|---|
| `<rect>` | `VisuFbElemSimple` (rectangle) | `x y width height` `class` |
| `<rect rx="…">` | `VisuFbElemSimple` (rounded) | same as rect + `rx` |
| `<circle>` | `VisuFbElemSimple` (ellipse) | `cx cy r` `class` |
| `<ellipse>` | `VisuFbElemSimple` (ellipse) | `cx cy rx ry` `class` |
| `<line>` | `VisuFbElemLine` | `x1 y1 x2 y2` `class` (always 1px — see Layout rules) |
| `<text>` | `VisuFbLabel` | `x`(=left) `y`(=**baseline**) `class` `font-size font-family` + textContent |
| `<rect data-cds-type="button">` | `VisuFbElemButton` | geometry + `data-text` (caption — a `<rect>` cannot carry text content) |
| `<text data-cds-type="textfield">` | `VisuFbElemTextfield` | `x y`(=**baseline**) `data-width data-height` `data-text-var` + textContent |

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
<text x="424" y="172" font-size="12"
      data-cds-type="textfield" data-width="336" data-height="32"
      data-text-var="HMI.Temperature">%3.2f C</text>
```
- `data-width` / `data-height` — bounding box (required; `<text>` has no
  native width/height).
- `y` is the **baseline**, not the box top: this field's box starts at
  `172 - 12 = 160`. Size it and place it on the grid through the box top.
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
- `stroke-width` — a CODESYS line has no width member. Draw a thick run as a
  `<rect>` instead.
- Table, TabControl, GroupBox, Checkbox, RadioButton,
  Scrollbar, SpinControl, ProgressBar, InvisibleInput

**Decompile-only** (read by `cts visu to-svg`, but cannot yet be authored with
`cts visu from-svg`): `slider`. Decompiling a real screen emits
`<rect data-cds-type="slider" ...>`; treat it as read-only when round-tripping.

**Frame** (embedded sub-visualization / faceplate) and **Dialog openers**
(open-dialog input-action with optional parameters) are fully supported for
both compile and decompile — see `reference/advanced-elements.md` for the
`capture-frame` workflow and the `data-open-dialog` / `data-dialog-param-*`
authoring syntax.

## Example — Pump Station sketch

Lints clean. Note the baselines: the field at `y="172"` has its box top at
`172 - 12 = 160`, 24px under the `y="148"` label above it.

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">

  <!-- header -->
  <text class="h1" x="24" y="46">Pump Station 1</text>
  <text class="caption" x="616" y="40" data-width="160" text-anchor="middle">Circuit A</text>
  <line class="divider" x1="24" y1="72" x2="776" y2="72"/>

  <!-- left: machine state -->
  <rect class="panel" x="24" y="88" width="368" height="296"/>
  <text class="h2" x="40" y="120">Motor</text>

  <rect data-cds-type="lamp" x="40" y="144" width="20" height="20"
        data-color="green" data-var="HMI.MotorRunning"/>
  <text class="label" x="72" y="160">Running</text>

  <rect data-cds-type="lamp" x="40" y="176" width="20" height="20"
        data-color="red" data-var="HMI.MotorFault"/>
  <text class="label" x="72" y="192">Fault</text>

  <rect class="card" x="40" y="224" width="336" height="96" rx="4"/>
  <rect class="ok" x="40" y="224" width="8" height="96"/>
  <text class="label" x="64" y="256">Speed</text>
  <text class="value" x="64" y="296">1 480</text>
  <text class="caption" x="176" y="295">rpm</text>

  <!-- right: live values -->
  <rect class="panel" x="408" y="88" width="368" height="296"/>
  <text class="h2" x="424" y="120">Temperatures</text>

  <text class="label" x="424" y="148">Bearing</text>
  <text data-cds-type="textfield" x="424" y="172" data-width="336" data-height="32"
        data-text-var="HMI.BearingTemp" font-size="12">%3.1f C</text>

  <text class="label" x="424" y="220">Oil</text>
  <text data-cds-type="textfield" x="424" y="244" data-width="336" data-height="32"
        data-text-var="HMI.OilTemp" font-size="12">%3.1f C</text>

  <rect class="alarm" x="424" y="304" width="336" height="48" rx="4"/>
  <text class="inverse" x="424" y="328" data-width="336" data-height="16"
        text-anchor="middle">Bearing over temperature</text>

  <!-- action row -->
  <line class="divider" x1="24" y1="392" x2="776" y2="392"/>
  <rect data-cds-type="button" x="24" y="408" width="160" height="48"
        data-text="Start Pump" data-cds-tap="TAP HMI.StartPump"/>
  <rect data-cds-type="button" x="200" y="408" width="160" height="48"
        data-text="Stop Pump" data-cds-tap="TAP HMI.StopPump"/>
</svg>
```
