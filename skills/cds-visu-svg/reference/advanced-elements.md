# Advanced elements (lamp, image-switcher, combobox, alarm-banner)

These are specialized native CODESYS controls. Use them only when the screen
genuinely needs that specific control — the core elements in `SKILL.md` cover
almost every screen. They compile and decompile through `cts visu from-svg` /
`cts visu to-svg` like the core elements, and their variables are auto-declared
by `--gvl` with the types listed here.

## Lamp

Indicator light bound to a BOOL. Colours: red, green, yellow, blue, gray.

```xml
<rect data-cds-type="lamp" data-color="red" data-var="HMI.PumpFault"
      x=".." y=".." width="32" height="32"/>
```

- `data-color` — one of `red`, `green`, `yellow`, `blue`, `gray` (default: `green`).
- `data-var` — BOOL variable that drives the On/Off state.
- GVL type: **BOOL**.

## ImageSwitcher

Two-state image toggle bound to a BOOL (pump/valve icons from the project
ImagePool).

```xml
<rect data-cds-type="image-switcher" data-image-on="ICONS.pump_run"
      data-image-off="ICONS.pump_stop" data-var="HMI.PumpRunning"
      x=".." y=".." width="70" height="70"/>
```

- `data-image-on` / `data-image-off` — ImagePool references in the form
  `Pool.name`.
- `data-var` — BOOL variable that selects which image is shown.
- GVL type: **BOOL**.

## ComboBoxInteger

Integer dropdown; labels come from a GlobalTextList entry.

```xml
<rect data-cds-type="combobox" data-items="'RECIPES'"
      data-var="HMI.Recipe" x=".." y=".." width="266" height="52"/>
```

- `data-items` — GlobalTextList reference for the item labels (single-quoted).
- `data-var` — INT variable, holds the selected index.
- GVL type: **INT**.

## AlarmBanner

Native scrolling alarm ticker driven from the project Alarm Configuration.
Geometry only — no variable binding.

```xml
<rect data-cds-type="alarm-banner" x=".." y=".." width="471" height="25"/>
```

- Attributes: geometry only (`x`, `y`, `width`, `height`).
- GVL: **none** (no variable declared).

## Not supported

Frame, Dialog, AlarmTable, Group, and Polygon are intentionally not supported
(too complex or rarely needed for sketch authoring) and will raise a clear error
if attempted.
