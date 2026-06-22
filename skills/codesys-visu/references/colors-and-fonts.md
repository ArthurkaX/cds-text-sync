# Colors & Fonts

> **Note for `cts visu` users:** The `cts visu` tool handles color encoding
> internally for supported types. Use this reference when hand-authoring XML
> for types not yet in the catalog, or when you need to understand the color
> struct encoding.

## Colors -- two encodings

CODESYS stores a color either as a packed **unsigned 32-bit ARGB integer**
(short form) or as a **full color struct** that also carries a style-linked
*canonical name*. Both appear in real files; pick by context.

### Short form (uint ARGB)

Used for direct fill/frame colors:

```xml
<Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">
  <Single Name="Id" Type="long">493260384</Single>
  <Single Name="Value" Type="uint">4294967295</Single>   <!-- 0xFFFFFFFF opaque white -->
</Single>
```

The `uint` is `0xAARRGGBB`. Common values:

| uint | hex | meaning |
|------|-----|---------|
| `4294967295` | `0xFFFFFFFF` | opaque white |
| `4278190080` | `0xFF000000` | opaque black |
| `4278255360` | `0xFF00FF00` | opaque green |
| `4294901760` | `0xFFFF0000` | opaque red |

### Full color struct (style-linked)

Used inside font descriptors and color lists. The `Color` is a **signed int32**
(the same ARGB bits reinterpreted as signed), and `CanonicalName` links it to a
named style color:

```xml
<Single Type="{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}" Method="IArchivable">
  <Single Name="Color" Type="int">-16777216</Single>            <!-- 0xFF000000 = black -->
  <Single Name="CanonicalName" Type="string">BasicElement-Frame-Color</Single>
</Single>
```

`-16777216` (int) == `4278190080` (uint) == `0xFF000000`. To convert a uint to
the signed int form: `signed = uint - 2**32 if uint >= 2**31 else uint`.

> **Never emit an empty `CanonicalName`.** CODESYS codegen asserts
> `!string.IsNullOrEmpty(name)` in
> `StylesNamedObjectsHelper.GetNamedObjectIdentifierExpr` and crashes on a
> color struct whose `CanonicalName` is an empty string. The IDE never emits an
> empty `CanonicalName` -- every color struct that participates in a named style
> carries one of the known names below. If a color is not style-linked, use the
> short-form `uint` encoding instead of a color struct.

#### Known CanonicalNames for textfield color members

These are the style names the IDE assigns to the color members of a
`VisuFbElemTextfield`:

| Member Id | Field | CanonicalName |
|-----------|-------|---------------|
| `494569607` | Frame / border color | `Element-Frame-Color` |
| `2812299069` | Fill color | `Element-Fill-Color` |

### Color list

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
