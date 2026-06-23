# Colors & Fonts

> **Note for `cts visu` users:** The `cts visu` tool handles color encoding
> internally for supported types. Use this reference when hand-authoring XML
> for types not yet in the catalog, or when you need to understand the color
> struct encoding.

## Colors -- two encodings

A color member is stored in one of **two forms**, and the form -- not the
`Color`/`Value` bits -- decides what CODESYS paints. Verified against
`_Basic.xml` (10 elements, 6 types); both forms appear in that single export, on
the **same member Id** (e.g. fill `2812299069`), so the type alone does not pick
the form.

- **(a) Named-style struct** `{fa491db2}` with a **non-empty `CanonicalName`** =>
  **style-linked**. CODESYS resolves the color from the named STYLE and
  **ignores the literal `Color` value**. Use this to keep the IDE's default
  themed color.
- **(b) Short-form `uint` scalar** `<Single Name="Value" Type="uint">ARGB</Single>`
  => **direct literal color**. The ARGB bits are painted as-is.

> **Root cause of "white / blank" synthesized elements.** A generator that
> emitted the named-style struct (form a) with a literal `Color` it *wanted*
> applied produced blank/white shapes: because `CanonicalName` was non-empty,
> CODESYS resolved from the style and discarded the literal, falling back to the
> style default (white fill). **To set a real color, emit the short-form `uint`
> (form b). To keep the IDE default themed color, keep the struct (form a).**
> This is both the failure mode and the customization mechanism.

### Short form (uint ARGB) -- direct literal color

```xml
<Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">
  <Single Name="Id" Type="long">2812299069</Single>      <!-- fill color -->
  <Single Name="Value" Type="uint">4294967295</Single>   <!-- 0xFFFFFFFF opaque white -->
</Single>
```

In `_Basic.xml` the circle `VisuFbElemSimple` (GenElemInst_6), the Image, and the
Frame all use this short form for fill `2812299069` / frame `494569607`.

The `uint` is `0xAARRGGBB`. Common values:

| uint | hex | meaning |
|------|-----|---------|
| `4294967295` | `0xFFFFFFFF` | opaque white |
| `4278190080` | `0xFF000000` | opaque black |
| `4278255360` | `0xFF00FF00` | opaque green |
| `4294901760` | `0xFFFF0000` | opaque red |

### Full color struct (style-linked) -- resolves from the style

The `Color` is a **signed int32** (the same ARGB bits reinterpreted as signed),
and a non-empty `CanonicalName` links it to a named style color (the literal
`Color` is then ignored on paint):

```xml
<Single Type="{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}" Method="IArchivable">
  <Single Name="Color" Type="int">-16777216</Single>            <!-- 0xFF000000 = black -->
  <Single Name="CanonicalName" Type="string">BasicElement-Frame-Color</Single>
</Single>
```

In `_Basic.xml` the rectangle and rounded-rect `VisuFbElemSimple`, the Line, all
three Polygons, and the Pie use this struct form for fill/frame.

### Signed int <-> unsigned uint ARGB

The struct's `Color` (`int`) and the short form's `Value` (`uint`) are the same
ARGB bits in two representations:

| signed int (struct) | unsigned uint (short) | hex | meaning |
|---------------------|-----------------------|-----|---------|
| `-1` | `4294967295` | `0xFFFFFFFF` | opaque white |
| `-16777216` | `4278190080` | `0xFF000000` | opaque black |
| `-65536` | `4294901760` | `0xFFFF0000` | opaque red |
| `-12337` | `4294954959` | `0xFFFFCFCF` | light pink (alarm fill default) |

`-16777216` (int) == `4278190080` (uint) == `0xFF000000`. To convert a uint to
the signed int form: `signed = uint - 2**32 if uint >= 2**31 else uint`.

> **Never emit an empty `CanonicalName`.** CODESYS codegen asserts
> `!string.IsNullOrEmpty(name)` in
> `StylesNamedObjectsHelper.GetNamedObjectIdentifierExpr` and crashes on a
> color struct whose `CanonicalName` is an empty string. The IDE never emits an
> empty `CanonicalName` -- every color struct that participates in a named style
> carries one of the known names below. If a color is not style-linked, use the
> short-form `uint` encoding instead of a color struct.

### CanonicalName prefix by element family (verified)

The named-style `CanonicalName` carries one of **two prefixes**, selected by the
element family -- and the two families even key their frame/alarm-frame colors on
**different member Ids**:

| Family | Element types | Color prefix | Frame Id | Alarm-frame Id |
|--------|---------------|--------------|----------|----------------|
| Basic shapes | `VisuFbElemSimple`, `VisuFbElemLine`, `VisuFbElemPolygon`, `VisuFbElemPie` | `BasicElement-*` | `494569607` | `135947015` |
| Composite | `VisuFbElemImage`, `VisuFbFrame` | `Element-*` | `2341735680` | `438423234` |

Observed `CanonicalName` values per member, by family:

- **Basic shapes** -- `494569607` => `BasicElement-Frame-Color`, `2812299069` =>
  `BasicElement-Fill-Color`, `135947015` => `BasicElement-Alarm-Frame-Color`,
  `493260384` => `BasicElement-Alarm-Fill-Color`, alarm-text `663104332` =>
  `Font-Default-Color`.
- **Image / Frame** -- `2341735680` => `Element-Frame-Color`, `438423234` =>
  `Element-Alarm-Frame-Color`. Note these elements simultaneously carry the
  Basic-prefix Ids (`494569607` / `2812299069` / `135947015` / `493260384`) in
  the **short `uint` form** -- a dual encoding within one element.

Some properties (e.g. Line control colors `2341735680` / `438423234`) wrap the
struct in a `<List Name="Value">`:

```xml
<Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">
  <Single Name="Id" Type="long">2341735680</Single>
  <List Name="Value" Type="System.Collections.ArrayList">
    <Single Type="{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}" Method="IArchivable">
      <Single Name="Color" Type="int">-16777216</Single>
      <Single Name="CanonicalName" Type="string">BasicElement-Frame-Color</Single>
    </Single>
  </List>
</Single>
```

### Known canonical names

```
BasicElement-Frame-Color        BasicElement-Fill-Color
BasicElement-Alarm-Frame-Color  BasicElement-Alarm-Fill-Color
Element-Frame-Color             Element-Fill-Color
Element-Alarm-Frame-Color       Element-Alarm-Fill-Color
Element-Button-FontColor        Element-Control-Color
Element-Background-Color        Element-Lamp-Lamp1-Red
Element-Switch-PushSwitchLed-Gray
Font-Default-Color              Font-Standard
```

## Fonts -- the descriptor

Property `3729828405` holds a one-item list containing a font struct
(`{9e842eb2-...}`). Copy this block verbatim and change `FontName` / `FontSize` /
`NamedColor`:

```xml
<Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">
  <Single Name="Id" Type="long">3729828405</Single>
  <List Name="Value" Type="System.Collections.ArrayList">
    <Single Type="{9e842eb2-1463-4af2-b605-4fbb17044f94}" Method="IArchivable">
      <Single Name="FontStyle" Type="int">0</Single>
      <Single Name="AdditionalFontStyle" Type="ushort">0</Single>
      <Single Name="ExplicitColor" Type="int">-16777216</Single>
      <Single Name="CanonicalName" Type="string">Font-Standard</Single>
      <Single Name="FontName" Type="string">Arial</Single>
      <Single Name="DisplayName" Type="string" />
      <Single Name="FontSize" Type="int">12</Single>
      <Single Name="ScriptIdentification" Type="int">0</Single>
      <Single Name="DoubleFontSize" Type="double">0</Single>
      <Single Name="NamedColor" Type="{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}" Method="IArchivable">
        <Single Name="Color" Type="int">-16777216</Single>
        <Single Name="CanonicalName" Type="string">Font-Default-Color</Single>
      </Single>
    </Single>
  </List>
</Single>
```

`FontStyle` bit flags: `0` normal, `1` italic, `2` bold (combinable). `FontSize`
is in points.
