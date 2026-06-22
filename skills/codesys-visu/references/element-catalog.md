# Element Catalog

> **Note for `cts visu` users:** This reference documents all 24 CODESYS
> visual element types in raw XML. The `cts visu` tool currently supports
> `VisuFbElemSimple` (rectangle shapes) via its catalog. Use this catalog when
> hand-authoring XML for other types, or when you need to understand an
> element's member structure.

The 24 element types CODESYS serializes. Each is a
`<Single Type="{f86c2928-...}">` block whose `VisualElementTypeName` is the type
name below. "Verified" types have a ground-truth `examples/` file extracted from
a real project; "documented" types are reconstructed from the reference and the
shared property model -- confirm them against the IDE before relying on them.

| # | Type | Purpose | Rect? | Status | Example |
|---|------|---------|:-----:|--------|---------|
| 1 | `VisuFbElemSimple` | Rectangle / circle / shape, optional text | yes | verified | `simple-rectangle.xml` |
| 2 | `VisuFbElemTextfield` | Text in/out field, value display & entry | yes | verified | `textfield.xml` |
| 3 | `VisuFbElemButton` | Button (ST snippet, dialog, inputbox), optional icon | yes | verified | `button.xml` |
| 4 | `VisuFbElemLine` | Line / polyline | no | verified | `line.xml` |
| 5 | `VisuFbElemPolygon` | Closed polygon / polyline, N points | no | verified | `polygon.xml` |
| 6 | `VisuFbElemImage` | Image from an image pool | yes | verified | `image.xml` |
| 7 | `VisuFbElemLamp` | ON/OFF lamp indicator | yes | verified | `lamp.xml` |
| 8 | `VisuFbElemTable` | Data table with columns (uses `SubElements`) | yes | verified | `table.xml` |
| 9 | `VisuFbElemAlarmTable` | Alarm history table | yes | verified | `alarm-table.xml` |
| 10 | `VisuFbElemAlarmBanner` | Scrolling alarm banner | yes | verified | `alarm-banner.xml` |
| 11 | `VisuFbElemRuntimeTrace` | Oscilloscope / time trace | yes | verified | `runtime-trace.xml` |
| 12 | `VisuFbElemPie` | Pie / gauge segment | no | documented | `pie.xml` |
| 13 | `VisuFbElemSpinControl` | Spin control (+/-) | yes | documented | `spin-control.xml` |
| 14 | `VisuFbElemPushSwitchLed` | Push button with integrated LED | yes | verified | `push-switch-led.xml` |
| 15 | `VisuFbElemScrollbar` | Scrollbar control | yes | verified | `scrollbar.xml` |
| 16 | `VisuFbElemSlider` | Slider control | yes | verified | `slider.xml` |
| 17 | `VisuFbElemDateTimePicker` | Date / time picker | yes | documented | `datetime-picker.xml` |
| 18 | `VisuFbFrame` | Embedded sub-visualization (references a frame) | yes | documented | `frame.xml` |
| 19 | `VisuFbGroup` | Group container with child elements | yes | documented | `group.xml` |
| 20 | `VisuFbLabel` | Static text label | yes | documented | `label.xml` |
| 21 | `VisuFbImageSwitcher` | Binary image toggle (ON/OFF) | yes | documented | `image-switcher.xml` |
| 22 | `VisuFbComboBoxInteger` | Integer dropdown | yes | documented | `combobox-integer.xml` |
| 23 | `VisuFbComboBoxArray` | Array dropdown | yes | documented | `combobox-array.xml` |
| 24 | `VisuFbGroupBox` | Group-box frame | yes | documented | `groupbox.xml` |

## Property sets used by each verified type

Only the *distinctive* properties are listed; all rectangular types also carry
X/Y/Width/Height plus the common fill/frame/border-width colors. Full ID meanings
are in [property-ids.md](property-ids.md).

- **Simple** -- shape style `564465120` (`VISU_ST_CIRCLE`, `VISU_ST_RECTANGLE`...),
  text `390574330`, text variable `2477733581`, border-color var `3450524324`,
  fill-color var `401380312`, font `3729828405`. When `390574330` is non-empty,
  a **Text ID** member `823443203` is also required (see
  [Text ID rule](#text-id-rule) below).
- **Textfield** -- text/format `390574330` (`%4.1f`), text variable `2477733581`,
  units variable `4168582468`, fill-color var `401380312`, text source
  `1337389588` (`FROM_STYLE`), color var `3450524324`. When `390574330` is
  non-empty, a **Text ID** member `823443203` is also required (see
  [Text ID rule](#text-id-rule) below). Often has an InputBox action (see
  [input-actions.md](input-actions.md)).
- **Button** -- label `390574330`, icon name `2478807622`, icon-color var
  `2175578022`, font `3729828405`. When `390574330` is non-empty, a **Text ID**
  member `823443203` is also required (see [Text ID rule](#text-id-rule) below).
  Action in `VisualElementInputActions` (ST snippet / dialog open).
- **Line** -- control colors `2341735680` / `438423234` (color lists),
  end-point pair `1357360684` / `669032122`.
- **Polygon** -- point style `564465120` (`VISU_PT_POLYLINE`), point coordinates
  in pairs (`1697884386`/`305436788`, `1481867602`/`794079684`,
  `536083330`/`1760873236`, `580112946`/`1435820708`...), visibility var
  `2880254039`.
- **Image** -- image id `3332245745` (`ImagePool.<name>`), scale mode `3549563837`
  (`ANISOTROPIC`, `ISOTROPIC`, `FIXED`), transparent flag `1651471674`.
- **Lamp** -- lamp image `4062784938` (`Element-Lamp-Lamp1-Red`), ON-condition
  variable `743958181`, ON color `2812299069`, OFF color `493260384`, text
  `296037572`, tooltip `571893170`.
- **Table** -- many bool layout flags; column data lives in the element's
  `SubElements` dictionary keyed `Columns.Column.[N].Template` (see
  [containers.md](containers.md)).
- **AlarmTable / AlarmBanner** -- column selector `3448851411`
  (`TIMESTAMP_LAST`, `MESSAGE`), ack/history bind vars `428520879`,
  `2607059081`, `3266827225`, font list `3729828405`.
- **RuntimeTrace** -- start `866368322`, stop `3851742229`, reset `3825648158`,
  display format `1134531926` (`%2.3f`).
- **PushSwitchLed** -- mode `1931512087` (`TAP`/`TOGGLE`), initial state
  `300685745`, lamp image `4062784938`, ON-condition var `743958181`.
- **Scrollbar** -- bound variable `1057716461`, max `2541109501`.
- **Slider** -- bound variable `397264524`, horizontal flag `3352862552`,
  enable expression `2496894244`, max `2541109501`.

## Documented (not yet ground-truth-verified) types

These follow the same skeleton and the shared geometry/color/font properties.
Treat the `examples/` for them as a structural starting point and confirm the
type-specific property IDs in the IDE:

- **Pie** -- non-rectangular; uses start/end angle and a center/radius geometry.
- **SpinControl** -- bound variable `397264524`, min `576042468`, max `651134158`,
  display format `1134531926`; typically an InputBox action.
- **DateTimePicker** -- bound variable plus a date/time format string.
- **Frame** -- references another visualization via
  `VisualElementFrameInformation` (see [containers.md](containers.md)).
- **Group / GroupBox** -- contain child elements in `SubElements`.
- **Label** -- static text in `390574330`, font `3729828405`.
- **ImageSwitcher** -- mode `1931512087`, initial state `300685745`, plus ON/OFF
  image ids.
- **ComboBoxInteger / ComboBoxArray** -- bound variable `397264524` plus the list
  source.

## Text ID rule

A `VisuFbElemSimple`, `VisuFbElemTextfield`, or `VisuFbElemButton` that carries
a non-empty text/format value in property `390574330` **MUST** also include a
`823443203` (Text ID) member. CODESYS rejects the import (*"One of the
identified items was in an invalid format"*) when this member is missing. The
Text ID is a string whose numeric value references an entry in the project
`GlobalTextList`; that entry must exist, or the IDE cannot resolve the text at
import time. A `VisuFbLabel` does **not** need `823443203` -- labels accept
literal text directly in `390574330`.

The member XML shape:

```xml
<Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">
  <Single Name="Id" Type="long">823443203</Single>
  <Single Name="Value" Type="string">912</Single>
</Single>
```

Examples that demonstrate the rule: `examples/textfield.xml`,
`examples/button.xml`, and the Textfield/Button elements in
`examples/full-screen.xml` and `examples/real-screen-wrapped.xml`. An element
whose `390574330` is empty (e.g. `examples/simple-rectangle.xml`) does not need
the Text ID.

## CanonicalName rule for color structs

A color struct (`{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}`) that participates in
a named style must carry a **non-empty** `CanonicalName`. CODESYS codegen
asserts `!string.IsNullOrEmpty(name)` in
`StylesNamedObjectsHelper.GetNamedObjectIdentifierExpr` and crashes when
`CanonicalName` is left empty -- the IDE never emits an empty `CanonicalName`.
Never write `<Single Name="CanonicalName" Type="string" />` in a color struct.
If the color is not style-linked, use the short-form `uint` ARGB encoding
instead (see [colors-and-fonts.md](colors-and-fonts.md)).

Known `CanonicalName` values for textfield color members: `494569607` ->
`Element-Frame-Color`; `2812299069` -> `Element-Fill-Color`. The full list of
known names is in [colors-and-fonts.md](colors-and-fonts.md).
