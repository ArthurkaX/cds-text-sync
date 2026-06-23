# Property IDs

> **Note for `cts visu` users:** This reference documents the raw CODESYS
> IArchivable XML serialization format. The `cts visu` tool handles property
> IDs internally for supported types; you only need these tables when
> hand-authoring XML for types not yet in the catalog, or when debugging
> generated output.

Every property inside `VisualElemMemberList` is a member block keyed by a numeric
**hash code** (`<Single Name="Id" Type="long">`). The IDs below are the
documented ones. **Never invent an ID** -- copy from a matching `examples/`
file or from this table.

The exact same ID means the same property across every element type that has it.

## How the Id is computed

`Id = zlib.crc32(CompletePath.encode("utf-8")) & 0xFFFFFFFF` (stored as `long`),
where `CompletePath` is the member's dotted path rooted at the element
(e.g. `m_StaticTexts.pstText`, `m_StaticColors.NormalColors.dwFillColor`). This is
the standard reflected zlib/ITU-T CRC-32 (verified against CODESYS 3.5.22.10 --
see [dotnet-ground-truth.md](dotnet-ground-truth.md)). The **CompletePath** column
below is filled in only where `crc32(path)` has been confirmed to equal the Id;
the verification table in `dotnet-ground-truth.md` re-verifies every such pair.

**Exceptions -- four Ids are overrides, NOT name hashes** (fixed `const long`
values or `ChecksumId` attribute overrides) and must never be validated against
crc32: `823443203` (Text ID), `3438453433` (Tooltip Id), `1225741287`
(`VISU_ST_STYLE`), `2478807622` (button icon). They are marked *override -- not
CRC* below.

## Geometry / universal

| Id | Field | Value type | CompletePath | Notes |
|----|-------|-----------|--------------|-------|
| `1649127785` | X (Left) | int | `m_StaticPosition.iX` | top-left origin, px |
| `357335551` | Y (Top) | int / short | `m_StaticPosition.iY` | |
| `2422045748` | Width | int / short | `m_StaticPosition.iWidth` | |
| `2134141914` | Height | int / short | `m_StaticPosition.iHeight` | |
| `550940142` | Center X | int | `m_StaticCenter.iX` | rotation pivot X; for simple rect/roundrect/pie/image == `X + Width//2` (verified `_Basic.xml`) |
| `1473355128` | Center Y | int | `m_StaticCenter.iY` | rotation pivot Y; == `Y + Height//2` for those types; NOT valid for line / polygon-point / frame elements |
| `2678395525` | Border width | uint / short | `m_StaticElementLook.iLineWidth` | usually `1` |
| `2340015797` | Horizontal align | string | `m_pStaticTextProperties..HorizontalAlignment` | `LEFT` / `HCENTER` / `RIGHT` |
| `2565699834` | Vertical align | string | `m_pStaticTextProperties..VerticalAlignment` | `TOP` / `VCENTER` / `BOTTOM` |
| `571893170` | Tooltip | string | `m_StaticTexts.pstToolTip` | |
| `2597686782` | Bool flag (likely visible) | bool | -- | `True` on every element in `_Basic.xml`; always the last member; meaning inferred as visible/enabled |
| `3719097617` | Angle / animation index | int | `m_StaticPosition.m_iAngle` | |
| `1337389588` | Shadow type | string | `m_ShadowType` | `NONE` / `FROM_STYLE` / ... |
| `1869484343` | Corner radius | short | `m_Radius.m_iRadius` | |
| `1651471674` | Show frame / Image keep-aspect | bool | `m_bShowFrame` | on `VisuFbElemImage` observed as a keep-aspect/transparent bool (`False` in `_Basic.xml`) |
| `300685745` | Initial state / tap false | bool | `m_bTapFalse` | toggle initial state (PushSwitchLed/ImageSwitcher) |
| `681815230` | Move complete | bool | `m_bMoveComplete` | |
| `3352862552` | Show scale | bool | `m_Scale.ShowScale` | |

## Colors

See [colors-and-fonts.md](colors-and-fonts.md) for the two encodings (uint
short-form vs full color struct / color list).

| Id | Field | Encoding | CompletePath | Notes |
|----|-------|----------|--------------|-------|
| `493260384` | Alarm fill color | uint or color struct | `m_StaticColors.AlarmColors.dwFillColor` | |
| `135947015` | Alarm frame color | uint or color struct | `m_StaticColors.AlarmColors.dwFrameColor` | |
| `2812299069` | Fill color / Lamp ON | uint or color struct | `m_StaticColors.NormalColors.dwFillColor` | |
| `494569607` | Frame / border color | uint or color struct | `m_StaticColors.NormalColors.dwFrameColor` | |
| `2341735680` | Control color (Line) | color list | `m_StaticColors.dwNormalColor` | |
| `438423234` | Control alarm-fill (Line/Scrollbar) | color list | `m_StaticColors.dwAlarmColor` | |
| `3488306084` | Frame color (uint alt) | uint | -- | |
| `2729990903` | Border color (uint) | uint | -- | |
| `2175578022` | Toggle normal color (Button/Textfield) | color struct | `m_pColorVariables..ColorVars.dwNormalColor` | |
| `1999528970` | Toggle color variable | string | `m_pColorVariables..ToggleColor` | placeholder `<toggle/tap variable>` on Simple/Line/Image/Frame in `_Basic.xml` (unset binding) |
| `4062784938` | Lamp / PushSwitchLed lamp image | string (`Element-Lamp-Lamp1-Red`) | `m_Background.m_stBitmapID` | |

## Fonts / text mode

| Id | Field | Value type | CompletePath | Notes |
|----|-------|-----------|--------------|-------|
| `3729828405` | Full font descriptor | `<List Name="Value">` of font struct | `m_pStaticTextProperties..Font` | |
| `1603690730` | Font name | string | -- | |
| `4253639993` | Font size | short | -- | |
| `663104332` | Alarm text color | color struct | `m_pStaticTextProperties..AlarmColor` | |
| `4134387352` | Text flag | string (`NONE`, ...) | `m_pStaticTextProperties..TextFlag` | verified `NONE` on all basic shapes in `_Basic.xml` |
| `3669839856` | Banner/table text align | string (`HCENTER`) | -- | |

## Text & variable bindings (shared)

| Id | Used by | Field | Value type | CompletePath | Notes |
|----|---------|-------|-----------|--------------|-------|
| `390574330` | Simple/Textfield/Button/Label | Text / format / label | string (`%s`, `%4.1f`, `Start`) | `m_StaticTexts.pstText` | |
| `2477733581` | Simple/Textfield | Text variable | string | `m_pTextChanges..pVarText` | |
| `3450524324` | Simple/Textfield | Border-color variable | string | -- | |
| `401380312` | Simple/Textfield/Pie | Fill-color variable | string | -- | |
| `4168582468` | All (tooltip) | Tooltip variable | string | `m_pTextChanges..pVarTooltip` | |
| `743958181` | General | Variable binding | string (boolean expr) | `m_pVariable..pVariable` | |
| `296037572` | Lamp/PushSwitchLed | Bitmap ON-state static ID | string | `m_BitmapInfo.m_stStaticIDON` | |
| `2880254039` | Polygon | Visibility variable | string | -- | |
| `1134531926` | RuntimeTrace/SpinControl | Format string | string (`%2.3f`) | `m_pFormat` | |
| `397264524` | SpinControl/Slider/ComboBox | Numeric bound variable | string | `m_pVariable..pVarNumber` | |
| `1057716461` | Current-value element | Current value variable | string | `m_pCurrentValue..pVarNumber` | |
| `2541109501` | Slider/Scrollbar/Combo | Page size variable | string | `m_prPageSize..pVarNumber` | |
| `1128707560` | Table/AlarmTable | Max array index variable | string | `m_pMaxArrayIndex..pVarNumber` | |

> **Text ID (`823443203`) is mandatory alongside non-empty `390574330`.** A
> `VisuFbElemSimple`, `VisuFbElemTextfield`, or `VisuFbElemButton` whose
> `390574330` value is a non-empty string MUST also carry a `823443203` member
> whose string value is a numeric Text ID registered in the project
> `GlobalTextList`. Without it CODESYS rejects the import with *"One of the
> identified items was in an invalid format."* A `VisuFbLabel` does NOT need
> `823443203` -- labels accept literal text directly in `390574330`. See
> [element-catalog.md](element-catalog.md) for the member shape.

## Element-specific

| Id | Element | Field | Value type | CompletePath | Notes |
|----|---------|-------|-----------|--------------|-------|
| `2478807622` | Button | Icon name | string (`ICONS.cross-mark`) | *override -- not CRC* | |
| `2175578022` | Button/Textfield | Toggle normal color | color struct | `m_pColorVariables..ColorVars.dwNormalColor` | |
| `1647042231` | Button | Button state variable | string | `m_pButtonStateVariable..DigitalVar` | |
| `823443203` | Simple/Textfield/Button | **Text ID** (GlobalTextList ref) -- required whenever `390574330` is non-empty; see note above | string (numeric, e.g. `912`) | *override -- not CRC* (`const long IdIextId`) | |
| `3438453433` | Button/Textfield | X / Y content offset / Tooltip Id | string | *override -- not CRC* (`const long IdTooltipId`) | |
| `3332245745` | Image | Image id | string (`ImagePool.<name>`) | `m_stStaticID` | in `_Basic.xml`: `VisuElemsWinControls.IP_ElementImages.Checkbox` |
| `3549563837` | Image | Scale mode | string (`ANISOTROPIC`/`ISOTROPIC`/`FIXED`) | `m_nIsotropicType` | verified `ANISOTROPIC` on Image |
| `1892739093` | Pie | Start angle | short | -- | verified `_Basic.xml` (`0`) |
| `3606942214` | Pie | Sweep / end angle | short | -- | verified `_Basic.xml` (`1`) |
| `1831690182` | Image/Frame | Transparency / alpha | short | -- | verified `_Basic.xml` (`-1`) |
| `2322377816` | Frame | Frame render mode | string (`NO_FRAME`) | -- | verified `_Basic.xml` |
| `394923068` | Frame | Bool flag | bool | -- | verified `_Basic.xml` (`False`); exact meaning unconfirmed |
| `1051212449` | Simple(circle)/Polygon/Line | Static-polygon type descriptor | `VisuStructPolygon` type tree | `m_StaticPositionPolygon` | structural node carrying the point sub-members; copy as a block |
| `363316305` | Frame | Reference-list type descriptor | `VisuStructReferenceList` type tree | `m_References` | carries the referenced-visualization sub-members; copy as a block |
| `3553112287` | Line/Simple(circle) | Line end style? | int | -- | verified present (`0`); meaning unconfirmed |
| `564465120` | Simple/Polygon | Shape / point style | string (`VISU_ST_CIRCLE`, `VISU_PT_POLYLINE`) | `m_StaticType` | |
| `1357360684` / `669032122` | Line | End-point X / Y | int | -- | |
| `1697884386` `305436788` `1481867602` `794079684` `536083330` `1760873236` `580112946` `1435820708` | Polygon | Point coordinate pairs | int | -- | |
| `866368322` | RuntimeTrace | Start variable | string | -- | |
| `3851742229` | RuntimeTrace | Stop variable | string | -- | |
| `3825648158` | RuntimeTrace | Reset trigger | string | -- | |
| `576042468` | SpinControl | Min value | string | -- | |
| `651134158` | SpinControl | Max value | string | -- | |
| `2496894244` | Slider | Enable expression | string | -- | |
| `1931512087` | PushSwitchLed/ImageSwitcher | Mode | string (`TAP`/`TOGGLE`) | `m_ElemType` | |
| `3448851411` | AlarmTable/Banner | Column selector | string (`TIMESTAMP_LAST`, `MESSAGE`) | -- | |
| `428520879` | AlarmTable | Ack selected variable | string | `m_AcknowledgementConfiguration.pAcknowledgeSelectedVariable` | |
| `2607059081` | AlarmTable | Ack all visible variable | string | `m_AcknowledgementConfiguration.pAcknowledgeAllVisibleVariable` | |
| `3266827225` | AlarmTable | History variable | string | `m_AcknowledgementConfiguration.pHistoryVariable` | |
| `3894972949` | AlarmTable | Freeze scroll pos variable | string | `m_AcknowledgementConfiguration.pFreezeScrollPosVariable` | |

## Seen in real IDE output (field name inferred)

These IDs were observed in CODESYS-IDE-exported screens but are not yet named
in CODESYS source; their meanings are inferred from the values that accompany
them. Listed so they are not flagged as undocumented. Confirm against the IDE
before relying on the value semantics.

| Id | Seen on | Observed value | Likely field |
|----|---------|---------------|--------------|
| `1225741287` | Simple | `VISU_ST_STYLE` | Shape style-mode name (*override -- not CRC*; ChecksumId attribute, not crc of `VISU_ST_STYLE`). Verified present on rect/roundrect Simple in `_Basic.xml`; absent from the circle Simple variant. |
| `2729990903` | Simple / Line / Polygon / Pie | `0` (uint) | **Unconfirmed** -- uint flag, always `0` in `_Basic.xml`; meaning not determined |
| `1213979116` | Simple / Textfield / Button | `0` (uint) | **Unconfirmed** -- uint flag, always `0`; meaning not determined |
| `3488306084` | Simple / Line / Polygon | `4278190080` (uint = `0xFF000000`) | **Unconfirmed** -- likely a text/secondary color (black), but not verified as such |

> Table-layout bool flags (`1981426263`, `3597700437`, `3479944212`,
> `129931535`, `3829854167`, `4250787478`, ...) and table size strings
> (`3736079596`, `1893244285`, `1494231439`, `4151883806`) appear in
> `examples/table.xml`; copy them as a block rather than setting individually.
