---
name: cds-visu-svg
description: >
  Generate SVG sketches for CODESYS visualization, conforming to the
  `cts visu from-svg` schema. Use when the user wants to create,
  modify, or debug SVG files that compile into CODESYS HMI screens.
---

# cds-visu-svg — SVG → CODESYS visu transpiler

The user has `cts visu from-svg` which compiles an SVG file directly into a
CODESYS visualization `.xml` file. Your job is to generate **valid SVG** that
this tool can consume, then attempt to compile it to a CODESYS visualization
object using `cts visu from-svg`.

## Workflow

1. **Generate the SVG** according to the rules below and write it to the project
   at the path the user requested (or a sensible default named after the screen,
   e.g. `<screen>.svg`).
2. **Try to compile it.** If `cts` is available in the environment, run:
   ```sh
   cts visu from-svg <path-to-svg> --help
   ```
   first to discover the required output path / options for the current project,
   then execute the actual compile command.  Prefer output names that match the
   target visualization object in the CODESYS project (commonly
   `Visu_<ScreenName>.xml` or a path under `project-view/`).
3. If `cts` is **not** available, report this clearly and provide the exact
   command the user can run manually.
4. Always report the compile result (success / error / not run).

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
  --surface:#…;   /* screen background */
  --primary:#…;   /* accent / main action colour */
  --frame:#…;     /* border / stroke colour */
  --text:#…;      /* font colour */
}
```

Full role set you may use (all optional): `background`, `surface`, `border`,
`text`, `text.muted`, `element.active`, `primary`, `secondary`, `accent`,
`on-surface`, `frame`, `success`, `warning`, `error`, `muted`.

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
- Use literal hex `#RRGGBB` / `#RRGGBBAA` when you want a specific colour.
- `<text fill="...">` controls **font colour** (the transpiler writes it as a literal uint).
- **Background colour** is controlled by `--surface` in `:root`.
  You do NOT need a separate rect for it.
- **Buttons** and **textfields** keep their colours style-linked —
  `fill`/`stroke` is used for browser preview but **ignored** by the transpiler,
  so the element inherits the project visual style.

## Data attributes for controls

### Button
```xml
<rect x="100" y="200" width="120" height="40" fill="var(--primary)"
      data-cds-type="button" data-text="Start" />
```
- `data-text` — button caption. The transpiler allocates a Text-ID in the
  GlobalTextList automatically.

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

## Text & Text-IDs

The transpiler **automatically** allocates Text-IDs for any element with
non-empty text and writes the entry to the project's `GlobalTextList`. You
do **not** need to specify a Text-ID yourself.

## Actions (Phase 6 — not yet compiled)

You may add `data-cds-tap` for documentation / design purposes, but the
transpiler does **not** compile it into CODESYS InputActions yet:

```xml
<rect data-cds-type="button" data-text="Stop" data-cds-tap="st: fbMotor.Stop();" .../>
```

Grammar: `st: <ST code>` or `toggle: <variable>`.

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

  <rect x="20" y="70" width="360" height="160" fill="var(--surface)" stroke="var(--frame)" stroke-width="2" rx="8"/>
  <text x="30" y="100" fill="var(--on-surface)" font-size="14" font-family="Arial">Motor: Running</text>
  <text x="30" y="130" fill="#888888" font-size="12" font-family="Arial">Speed: 1450 RPM</text>

  <circle cx="330" cy="100" r="20" fill="var(--success)"/>

  <rect x="20" y="260" width="160" height="50" fill="var(--primary)"
        data-cds-type="button" data-text="Start Pump"/>
  <rect x="200" y="260" width="160" height="50" fill="var(--warning)"
        data-cds-type="button" data-text="Stop Pump"/>

  <text x="20" y="260" font-size="14" font-family="Arial"
        data-cds-type="textfield" data-width="200" data-height="30"
        data-text-var="HMI.Temperature" fill="var(--warning)">%3.1f C</text>

  <line x1="20" y1="340" x2="780" y2="340" stroke="var(--frame)" stroke-width="1"/>

  <text x="20" y="420" fill="var(--on-surface)" font-size="14" font-family="Arial">Alarms</text>
  <rect x="20" y="435" width="180" height="30" fill="var(--surface)" stroke="var(--success)" stroke-width="1"/>
  <text x="28" y="454" fill="var(--success)" font-size="11" font-family="Arial">Level Sensor OK</text>
  <rect x="210" y="435" width="180" height="30" fill="var(--surface)" stroke="var(--warning)" stroke-width="1"/>
  <text x="218" y="454" fill="var(--warning)" font-size="11" font-family="Arial">Temp High Warning</text>
</svg>
```
