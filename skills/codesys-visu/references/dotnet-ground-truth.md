# CODESYS Visualization XML -- .NET Ground Truth

> **Note for `cts visu` users:** This reference documents the .NET reverse
> engineering that confirmed the member hash formula and serialization GUIDs.
> It is the underlying research -- not needed for daily use of `cts visu`, but
> valuable when debugging or extending the catalog.

**Extracted from:** CODESYS 3.5.22.10 .NET assemblies
**Tool:** `dnfile` 0.18.0 (pure Python .NET PE metadata parser -- no CLR needed)
**Date:** 2026-06-21

## Methodology

- Parsed TypeDef, Field, MethodDef, CustomAttribute (table 12), InterfaceImpl (table 9), Constant (table 11),
  MemberRef (table 10), and #GUID heap from the assemblies' .NET metadata tables.
- Resolved CustomAttribute blobs to extract int64 hash IDs and binary GUIDs.
- Searched #GUID heap and #Strings heap for known XML serialization GUIDs.
- **Limitation:** Cannot load CLR due to unresolved CODESYS PE dependencies (Controls, Compiler, etc.).
  All extraction is metadata-only -- no code decompilation.

## Assemblies Scanned

| Assembly | Path | TypeDefs | Version |
|----------|------|----------|---------|
| Objects.dll | `...\CODESYS\Common\Objects.dll` | 347 | 3.5.22.10 |
| VisualEditor.plugin.dll | `...\PlugIns\01bcdb4a-...\4.9.1.0\VisualEditor.plugin.dll` | 1083 | 4.9.1.0 |
| VisualStyles.plugin.dll | `...\PlugIns\30fbd6bb-...\4.9.1.0\VisualStyles.plugin.dll` | 316 | 4.9.1.0 |
| VisualStyles.dll (Common) | `...\CODESYS\Common\VisualStyles.dll` | 53 | 4.9.1.0 |
| VisualObject.dll | `...\CODESYS\Common\VisualObject.dll` | 346 | 4.9.1.0 |

Additional DLLs with VisuFb references: `VisuGenerated.plugin.dll`, `VisualElemRepository.plugin.dll`,
`VisuElementImplementationExtensions.plugin.dll`, `VisuInterfaceExtensions.dll`, `VisuGenerated.dll`,
`TrendRecordingObjects.plugin.dll`, `AlarmConfigurationObjects.plugin.dll`.

## Key Finding: VisuFbElem* Types NOT Found as .NET TypeDefs

The concrete visualization element types (VisuFbElemTextfield, VisuFbElemButton, VisuFbElemLamp,
VisuFbLabel, VisuFbElemSimple, VisuFbElemRectangle, etc.) are **NOT defined as TypeDefs** in any scanned
assembly. They are referenced via TypeRef in some assemblies (e.g., `IVisuFbSimpleRectangleList` in
VisuGenerated.dll), which suggests they are defined in a CODESYS compiled library (`.library` file)
rather than a .NET assembly, or are generated at runtime.

The serialization contract (IArchivable + member hash IDs) is the ground truth for how these types
serialize to XML.

## 1. IArchivable Serialization Contract

### IArchivable Interface (`_3S.CoDeSys.Core.Objects`)

**Defined in:** Objects.dll v3.5.22.10
**Namespace:** `_3S.CoDeSys.Core.Objects`

**Methods (from TypeDef method table):**
- `get_SerializableValueNames` -- returns list of serializable value names
- `GetSerializableValue` -- gets a value by name
- `SetSerializableValue` -- sets a value by name
- `BeforeSerialize` -- pre-serialization hook
- `AfterDeserialize` -- post-deserialization hook

This is a name-value pair serialization pattern, not a simple Read/Write/GetId.

**Extended by:**
- `IArchivable2` through `IArchivable6` (same namespace, same assembly) with additional methods

**Implementors (in Objects.dll):**
- `GenericObject`, `GenericObject2`
- `IMetaObject` through `IMetaObject9`
- `IObjectProperty`, `IObjectAccessProperty`, `IObjectAccessProperty2`
- `IFolderObject`, `ISVFoldersProperty`
- `IDocumentationProperty`, `IEmbeddedObject`, `IGenericObject`
- `IObject`, `IObject2`, `IUnknownObject`, `IUnknownObject2`

## 2. Known XML Serialization GUIDs

The following GUIDs are known empirically from visualization XML files but were **NOT found as literal
strings** in the #Strings heap of any scanned assembly. They exist as binary GUID values (16 bytes)
in the #GUID heap and are referenced programmatically by the serialization code.

| GUID | Role | Found in #Strings? |
|------|------|--------------------|
| `{f86c2928-8614-4cca-824b-e819ac4d58c4}` | Element Type wrapper | NOT FOUND -- confirmed as embedded schema-table literal |
| `{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}` | Member/Property wrapper | NOT FOUND |
| `{17e26cd1-bb9b-47fe-a3d5-18fcd63b9c96}` | VisualElemMemberList wrapper | NOT FOUND |
| `{a4b83bea-3742-489c-9fe8-d96d68dba7ab}` | List (generic collection) | NOT FOUND |
| `{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}` | Color struct | NOT FOUND |

The #GUID heap of Objects.dll contains only one entry: `C4AB33C9-6EAF-41B3-AAC4-D5A805B67500`.

**Conclusion:** These GUIDs are likely registered at runtime through CODESYS' plugin/extensibility system
or are embedded in serialization code rather than stored as assembly metadata strings.

## 3. Member Hash ID Mechanism

### IecVisualElemMemberConstants

**Class:** `VisuUtilities.IecVisualElemMemberConstants` (defined in VisualEditor.plugin.dll)

**Fields (5):**
| Field Name | Constant Value in Metadata |
|-----------|--------------------------|
| `InputHandler` | (no constant -- runtime initialized) |
| `FrameReferences` | (no constant -- runtime initialized) |
| `StaticAngle` | (no constant -- runtime initialized) |
| `StaticPositionAngle` | (no constant -- runtime initialized) |
| `ForwardInputs` | (no constant -- runtime initialized) |

**Critical finding:** The Constant table (table 11) does NOT contain compile-time constant values for
any of these fields. This means the hash values are assigned at runtime, likely in a static constructor
or from an external resource.

### Hash ID Custom Attributes

**No custom attributes encoding member hash IDs were found on any fields** in any scanned assembly.

### Known Hash IDs (Empirical)

Based on existing XML samples and code analysis (not directly confirmed from assembly metadata):

| Hash ID (decimal) | Hash ID (hex) | Likely Member | Description |
|-------------------|---------------|---------------|-------------|
| 390574330 | 0x1746E6FA | Text | Textfield content |
| 823443203 | 0x31161803 | TextId | Text ID / textlist reference |
| 2477733581 | 0x93AB6A0D | TextVariable | Text variable binding |
| 494569607 | 0x1D79E4C7 | FrameColor / nFrameColor | Frame/border color |
| 2812299069 | 0xA7A2013D | FillColor / nFillColor | Fill/background color |

## 4. Visual Styles: Color Struct and Named Objects

### IStylesNamedObjectsHelper Interface

**Defined in:** `_3S.CoDeSys.VisualStyles.IStylesNamedObjectsHelper` (VisualStyles.dll in Common)

**Methods:**
- `GetNamedObjectIdentifier` (appears twice -- likely overloaded: by name and by object)

This confirms the `StylesNamedObjectsHelper` referenced in the assertion error
(`!string.IsNullOrEmpty(name)` in `GetNamedObjectIdentifierExpr`). The rule is:
- When `CanonicalName` is non-empty: the color references a named style object
- When `CanonicalName` is empty: the `Color` field contains the literal ARGB value

### Known Color Struct Members (from empirical XML analysis)

The `{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}` color struct contains (confirmed empirically):
- `Color` (int) -- ARGB value when no named style
- `CanonicalName` (string) -- named style reference; must be non-empty for named styles

## 5. Style Types in VisualStyles.plugin.dll

The VisualStyles.plugin.dll (v4.9.1.0, 316 TypeDefs) contains:
- `VisualizationStyleItem` -- main style item class
- Nested types: `.UnavailableStyleItem`, `.NoStyleItem`, `.DefaultStyleItem`, `.LastUsedStyleItem`, `.StyleItem`, `.BaseStyleItem`

All types are in the `_3S.CoDeSys.VisualStyles` namespace.

## 6. XML Element Skeleton (Empirical)

Based on existing XML file analysis, the visualization element serialization follows this structure:

```
<Single Type="{element-type-guid}" Method="IArchivable">
  <Single Type="{17e26cd1-bb9b-47fe-a3d5-18fcd63b9c96}">        <!-- VisualElemMemberList -->
    <List Type="{a4b83bea-3742-489c-9fe8-d96d68dba7ab}">       <!-- generic list of members -->
      <Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}">   <!-- member wrapper -->
        <Single Name="Id" Type="long">HASH_ID</Single>
        <Single Name="Value" Type="...">VALUE</Single>
      </Single>
      ...more members...
    </List>
  </Single>
  <Single>...ConfiguredComplexInputs...</Single>
  <Single>...Elements (child elements)...</Single>
  <Single>...VisualElementDescription (position/size)...</Single>
</Single>
```

## 7. Hash Algorithm Status

**NOT determined from assembly metadata.** No hash computation function was identified in the scanned
assemblies, and the member hash IDs are not stored as compile-time constant values.

The hash is believed to be a CODESYS-specific stable hash of the member name (not .NET GetHashCode,
not Java hashCode). To determine the exact formula, one would need to either:
1. Decompile the hash function implementation (using ILSpy/ildasm with proper dependency resolution)
2. Reverse-engineer from known name-to-hash pairs by testing common hash algorithms
3. Write a test program that loads the CODESYS assemblies via CLR and queries member IDs at runtime

## Summary

| Item | Status | Source |
|------|--------|--------|
| IArchivable interface | Confirmed in Objects.dll v3.5.22.10 | TypeDef + method table |
| IArchivable methods | `get_SerializableValueNames`, `GetSerializableValue`, `SetSerializableValue`, `BeforeSerialize`, `AfterDeserialize` | MethodDef table |
| Element type GUIDs | NOT found as strings in #Strings heap | String heap scan |
| Member wrapper GUID `{c694e3a2...}` | NOT found | String heap scan |
| VisualElemMemberList GUID `{17e26cd1...}` | NOT found | String heap scan |
| List GUID `{a4b83bea...}` | NOT found | String heap scan |
| Color struct GUID `{fa491db2...}` | NOT found | String heap scan |
| IecVisualElemMemberConstants | Confirmed, but constant values are runtime-initialized (not in Constant table) | TypeDef + Constant table |
| Hash ID custom attributes | NONE found on any field in any assembly | CustomAttribute table scan |
| VisuFbElem* TypeDefs | NOT found in any scanned assembly | Full assembly search (3161 DLLs) |
| CanonicalName rule | Confirmed via IStylesNamedObjectsHelper | TypeDef + method table |
| Hash algorithm | NOT determined | N/A |

## ILSpy decompilation (method bodies)

**Tool:** ICSharpCode.Decompiler 10.1.0.8386 driven from Python via pythonnet 3.1.0
  on the system .NET 8 CoreCLR.
**Date:** 2026-06-22

### Target 1 (partial) -- IecVisualElemMemberConstants is NAME constants, NOT IDs

**Assembly:** `VisualEditor.plugin.dll` (4.9.1.0)
**Namespace:** `VisuUtilities`  **Class:** `internal static class IecVisualElemMemberConstants`

Decompiled verbatim (whole class):

```csharp
namespace VisuUtilities;

internal static class IecVisualElemMemberConstants
{
    public const string InputHandler = "m_pInputHandler";
    public const string FrameReferences = "m_References";
    public const string StaticAngle = "m_iAngle";
    public const string StaticPositionAngle = "m_StaticPosition.m_iAngle";
    public const string ForwardInputs = "ForwardInputs";
}
```

**Correction to the dnfile-era finding:** The 5 fields in this class are `const string`
member NAMES, not numeric hash IDs. The dnfile scan reported "constant values are
runtime-initialized" because dnfile does not surface string-constant fields from the
Constant table the same way; in fact they ARE compile-time `const string` literals
shown above. The numeric `Id` values (390574330 etc.) are NOT defined here -- they are
computed elsewhere from these (and other) member-name strings. The hash-formula
search is in progress; see Target 1b below.

Additional member-name constant classes found in the same assembly
(`_3S.CoDeSys.VisualEditor.VisuElemMemberAttributes`, abstract) define more
serializable member NAME strings, e.g.:

```csharp
public abstract class VisuElemMemberAttributes
{
    public static class FontAttributes {
        public const string Name = "FontName";
        public const string Height = "FontHeight";
        public const string Flags = "FontFlags";
        public const string Charset = "FontCharset";
        public const string Color = "FontColor";
    }
    public const string Clipping = "Clipping";
    public const string ClippingGroupBox = "ClippingGroupBox";
    public const string DrawFrame = "DrawFrame";
    public const string ScaleType = "ScaleType";
    public const string FrameReferences = "FrameReferences";
    public const string FrameColorStructureNode = "DrawFrameColor";
    public const string FrameLineStyle = "DrawFrameStyle";
    public const string FrameLineWidth = "DrawFrameWidth";
    public const string DrawText = "DrawText";
    public const string TextHorizontalAlignment = "TextHorizontalAlignment";
    public const string TextVerticalAlignment = "TextVerticalAlignment";
    public const string OfflineTextProperties = "OfflineTextProperties";
    public const string PaintOffsetDirection = "PaintOffsetDirection";
    ... (more)
}
```

Also found: `VisuUtilities.ObjectTypeGuids` defines
`public static readonly Guid TEXTLIST_PROPERTY_TYPEGUID = new Guid("{9DB18249-9FCF-4264-A9DE-410A659A36B3}");`
and `_3S.CoDeSys.VisualEditor.Guids` defines editor-command GUIDs (EditUndo, EditRedo,
ToolboxViewFactory, VisualPropertyGuid `{477D844B-9B2A-407E-90A4-D36FD6DDE2FC}`, etc.).
None of these match the 5 serialization wrapper GUIDs from Target 2 -- the search
for the wrapper-GUID literals continues.

### Target 1b -- THE MEMBER-HASH FORMULA (VERIFIED)

**Assembly:** `VisualElem.plugin.dll` (4.9.1.0)
**Namespace:** `_3S.CoDeSys.VisualElem`  **Class:** `public abstract class TypeNode`

The numeric `Id` written as `<Single Name="Id" Type="long">` is **CRC-32 of the
member's `CompletePath` dotted string** (UTF-8), using the standard zlib/ITU-T
CRC-32 (reflected, polynomial 0xEDB88320, init 0xFFFFFFFF, final XOR 0xFFFFFFFF --
i.e. Python `zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF`). The result is stored
as an unsigned 32-bit value widened into the `long` `Id` field.

Decompiled verbatim, the call site and the path builder:

```csharp
// _3S.CoDeSys.VisualElem.TypeNode, VisualElem.plugin.dll
public string CompletePath
{
    get
    {
        if (this is BasicTypeNode && ((BasicTypeNode)this).HasFlag((BasicTypeNodeFlags)16))
        {
            return m_stName;
        }
        string text = m_stName;
        for (ITypeNode parent = (ITypeNode)(object)m_Parent; parent != null; parent = parent.Parent)
        {
            text = parent.Name + "." + text;
        }
        return text;
    }
}

public long CRCIdNumber => _lId;

public void UpdateCRCIdNumber()
{
    if (_suppressUpdateCrC || (this is BasicTypeNode && ((BasicTypeNode)this).HasFlag((BasicTypeNodeFlags)16)))
    {
        return;
    }
    if (Attributes.HasAttribute("ChecksumId"))
    {
        try
        {
            string attributeValue = Attributes.GetAttributeValue("ChecksumId");
            if (attributeValue.StartsWith("0x"))
                _lId = long.Parse(attributeValue.Substring(2), NumberStyles.HexNumber);
            else
                _lId = long.Parse(attributeValue);
        }
        catch
        {
            _lId = Utilities.CalculateCrc32(CompletePath);
        }
    }
    else
    {
        _lId = Utilities.CalculateCrc32(CompletePath);
    }
    if (_sId == TypeTreeGenerator.INVALID_ID)
    {
        _sId = (short)_lId;
        _sId &= 4095;
        _sId |= 2048;
    }
    foreach (TypeNode alChild in m_alChildren)
        alChild.UpdateCRCIdNumber();
}

public void UpdateCRCIdNumberWithPrefix(string stPrefix)
{
    if (stPrefix == null) throw new ArgumentNullException("stPrefix");
    _lId = Utilities.CalculateCrc32(stPrefix + CompletePath);
    foreach (TypeNode alChild in m_alChildren)
        alChild.UpdateCRCIdNumberWithPrefix(stPrefix);
}
```

The member is constructed with the CRC as its Id -- from
`_3S.CoDeSys.VisualElem.VisualElemMemberListGeneratorVisitor.CreateVisualElemMember`
(same assembly), every `new VisualElemMember(...)` is passed `node.CRCIdNumber`
as the Id, and `UpdateCRCIdNumber()` is called on every `visit(...)` before
creation:

```csharp
// VisualElemMemberListGeneratorVisitor
public void visit(IBasicTypeNode node)
{
    ((TypeNode)(object)node).UpdateCRCIdNumber();
    CreateVisualElemMember((ITypeNode)(object)node);
}
// ... and similarly for IPointerTypeNode, IArrayTypeNode, IStructuredTypeNode,
// IDynamicArrayNode, IVisualizationNode -- each calls UpdateCRCIdNumber() then
// CreateVisualElemMember, which does:
//   visualElemMember = new VisualElemMember(node.CRCIdNumber, node.CompletePath, value);
```

`Utilities.CalculateCrc32` is defined in `_3S.CoDeSys.VisualElem.Utilities` (same
assembly). Its method body could NOT be decompiled: ILSpy 10.1 throws a
`CustomAttributeDecoder` exception during `RequiredNamespaceCollect` on this
specific type (a corrupt/undecodable attribute blob on one of its members), and
no `DecompilerSettings` toggle skips that pass. This is NOT blocking -- the
algorithm is confirmed empirically below as standard zlib CRC-32.

#### Verification (Python `zlib.crc32(path.encode("utf-8")) & 0xFFFFFFFF`)

All pairs PASS -- the formula is confirmed:

| CompletePath (hashed string) | Computed CRC-32 | Expected Id | Result | Member |
|------------------------------|-----------------|-------------|--------|--------|
| `m_StaticTexts.pstText` | 390574330 | 390574330 | PASS | Text (Simple/Textfield/Button/Label) |
| `m_StaticTexts.pstToolTip` | 571893170 | 571893170 | PASS | Tooltip |
| `m_pTextChanges..pVarText` | 2477733581 | 2477733581 | PASS | Text variable |
| `m_StaticPosition.iX` | 1649127785 | 1649127785 | PASS | X (Left) |
| `m_StaticPosition.iY` | 357335551 | 357335551 | PASS | Y (Top) |
| `m_StaticPosition.iWidth` | 2422045748 | 2422045748 | PASS | Width |
| `m_StaticPosition.iHeight` | 2134141914 | 2134141914 | PASS | Height |
| `m_StaticElementLook.iLineWidth` | 2678395525 | 2678395525 | PASS | Border width |
| `m_StaticColors.NormalColors.dwFillColor` | 2812299069 | 2812299069 | PASS | Fill color / Lamp ON |
| `m_StaticColors.NormalColors.dwFrameColor` | 494569607 | 494569607 | PASS | Frame / border color |
| `m_pStaticTextProperties..Font` | 3729828405 | 3729828405 | PASS | Full font descriptor |
| `m_StaticType` | 564465120 | 564465120 | PASS | Shape (`VISU_ST_CIRCLE`) |
| `m_pStaticTextProperties..HorizontalAlignment` | 2340015797 | 2340015797 | PASS | Horizontal align |
| `m_StaticColors.dwAlarmColor` | 438423234 | 438423234 | PASS | Control alarm-fill color |
| `m_StaticColors.dwNormalColor` | 2341735680 | 2341735680 | PASS | Control color (Line) |
| `m_Background.m_stBitmapID` | 4062784938 | 4062784938 | PASS | Lamp/PushSwitchLed lamp image |
| `m_ElemType` | 1931512087 | 1931512087 | PASS | PushSwitchLed/ImageSwitcher Mode |

**17/17 PASS.** The `CompletePath` string is the dotted member path rooted at the
element (e.g. `m_StaticTexts.pstText`, `m_StaticPosition.iX`). The
`VisualElemMember` const-string fields (`TEXT = "m_StaticTexts.pstText"`,
`POSITION_X = "m_StaticPosition.iX"`, `FILL_COLOR = "m_StaticColors.NormalColors.dwFillColor"`,
etc., in `_3S.CoDeSys.VisualElem.VisualElemMember`) are exactly these CompletePath
strings -- so a member's Id is `crc32(VisualElemMember.<CONST>)`.

#### Non-CRC "well-known" Ids (NOT name hashes)

Four documented Ids are NOT CRC-32 of any reachable CompletePath string and are
instead fixed/synthetic well-known IDs:

- **`823443203`** -- `Text ID` / `IextId`. Defined as
  `public const long IdIextId = 823443203L;` in `VisualElemMember`. Also produced
  by the `IdForSave` setter, which remaps legacy serialized Ids:
  `case 3750217316L: _Id = 823443203L;` (i.e. older archives stored `3750217316`
  for this member; on read it is rewritten to the current well-known Id).
- **`3438453433`** -- `TooltipId` / X-Y content offset. Defined as
  `public const long IdTooltipId = 3438453433L;` and via
  `case 2953584269L: _Id = 3438453433L;` in the same setter.
- **`1225741287`** -- `VISU_ST_STYLE` shape style (observed). Not a CRC of
  `VISU_ST_STYLE` (that hashes to `3950723613`). This is a `ChecksumId`
  attribute override on the style TypeNode (the `Attributes.HasAttribute("ChecksumId")`
  branch above parses the literal instead of computing CRC), or a legacy alias.
- **`2478807622`** -- Button icon name. Same: not a CRC of any obvious bitmap/icon
  path (`m_Background.m_stBitmapID` hashes to `4062784938`); it is a `ChecksumId`
  override or a separate well-known constant.

The `IdForSave` setter (`VisualElemMember.IdForSave`) full body, showing the
legacy-id remap (these legacy ids are NOT CRCs of current names either -- they
are prior-version hashes retained only for backward-compatible deserialization):

```csharp
[DefaultSerialization("Id")]
[StorageVersion("3.3.0.0")]
protected long IdForSave
{
    get { return _Id; }
    set
    {
        switch (value)
        {
        case 3096537052L: _Id = 390574330L; break;   // legacy text -> current Text
        case 3206511478L: _Id = 571893170L; break;   // legacy tooltip -> current Tooltip
        case 3750217316L: _Id = 823443203L; break;   // legacy -> TextId (IextId)
        case 2953584269L: _Id = 3438453433L; break;  // legacy -> TooltipId
        default:         _Id = value; break;
        }
    }
}
```

**Summary formula:** `Id = zlib.crc32(CompletePath.encode("utf-8")) & 0xFFFFFFFF`
(stored as `long`), with an opt-out `ChecksumId` attribute that pins a member to
a literal id, and a small set of legacy-id remaps applied on deserialization.

### Target 2 -- the 5 wrapper GUIDs

All five are `[TypeGuid("...")]` attributes (resolved by the decompiler from the
#Blob heap -- which is why the dnfile #Strings scan missed them). Four of the five
are confirmed on specific classes in `VisualElem.plugin.dll`; the fifth (the
element wrapper) belongs to a class not present in any .NET assembly.

Decompiled declarations verbatim:

```csharp
// _3S.CoDeSys.VisualElem.VisualElemMember, VisualElem.plugin.dll
[DebuggerDisplay("{DebugInfo}")]
[TypeGuid("{C694E3A2-5C0B-4177-AB35-CB06BD5A6A02}")]
[StorageVersion("3.3.0.0")]
public class VisualElemMember : GenericObject2, IVisualElemMember
{
    // the <Single Type="{c694e3a2-...}"> member struct (Id + Value)
    ...
}

// _3S.CoDeSys.VisualElem.VisualElemMemberList, VisualElem.plugin.dll
[TypeGuid("{17E26CD1-BB9B-47fe-A3D5-18FCD63B9C96}")]
[StorageVersion("3.3.0.0")]
public class VisualElemMemberList : GenericObject2, IVisualElemMemberList, IEnumerable
{
    // the <Single Type="{17e26cd1-...}"> VisualElemMemberList wrapper
    ...
}

// _3S.CoDeSys.VisualElem.VisualElemMemberCollection, VisualElem.plugin.dll
[TypeGuid("{A4B83BEA-3742-489c-9FE8-D96D68DBA7AB}")]
[StorageVersion("3.3.0.0")]
public class VisualElemMemberCollection : CollectionBase, ICloneable
{
    // the <List Type="{a4b83bea-...}"> inner list
    ...
}

// _3S.CoDeSys.VisualElem.NamedStyleColor, VisualEditor.plugin.dll-dep chain, VisualElem.plugin.dll
[TypeGuid("{FA491DB2-51FF-4bc1-9CD0-CE8C94FF6216}")]
[StorageVersion("3.4.4.0")]
[DebuggerDisplay("NamedStyleColor {_stCanonicalName}: {_color}")]
public class NamedStyleColor : GenericObject2, INamedStyleColor2, INamedStyleColor, INamedStyleObject
{
    // the {fa491db2-...} color struct (Color int + CanonicalName string)
    ...
}
```

#### The element wrapper `{f86c2928-8614-4cca-824b-e819ac4d58c4}` -- CONFIRMED

This GUID is the TypeGuid of the **ROOT visual-element serialization wrapper** -- the
envelope that carries the 14 `VisualElement*` members (ConfiguredComplexInputs, Elements,
VisualElementDescription, VisualElementName, VisualElementTypeName,
VisualElementIsRectangle, VisualElementIdentifier, VisualElementOfflinePaintCommands,
VisualElementFrameInformation, VisualElementInputActions, VisualElementIdentification,
VisualElementOwningObjectGuid, SubElements, UserManagementAccessRights). It is the
SAME GUID for all elements, not per-element.

It is **NOT** a `[TypeGuid]` attribute on any .NET TypeDef in the scanned assemblies
-- instead it lives as an embedded schema-table literal in:
- `VisualStyles.plugin.dll` at binary offset ~0x84E15
- `VisualElemRepository.plugin.dll` at offsets ~0x11E757 and ~0x1438DA

These occurrences are registered at runtime (not loaded from assembly metadata
strings), which is why the earlier `dnfile` / metadata-only scan missed them.

#### Target 2 summary

| GUID | Role | `[TypeGuid]` on class | Source |
|------|------|------------------------|--------|
| `{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}` | member struct (Id+Value) | `VisualElemMember` | CONFIRMED, VisualElem.plugin.dll |
| `{17e26cd1-bb9b-47fe-a3d5-18fcd63b9c96}` | VisualElemMemberList wrapper | `VisualElemMemberList` | CONFIRMED, VisualElem.plugin.dll |
| `{a4b83bea-3742-489c-9fe8-d96d68dba7ab}` | inner list | `VisualElemMemberCollection` | CONFIRMED, VisualElem.plugin.dll |
| `{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}` | color struct | `NamedStyleColor` | CONFIRMED, VisualElem.plugin.dll |
| `{f86c2928-8614-4cca-824b-e819ac4d58c4}` | root VisualElement* wrapper (14 members) | embedded schema-table literal | CONFIRMED -- not a .NET `[TypeGuid]`; embedded in VisualStyles.plugin.dll (~0x84E15) and VisualElemRepository.plugin.dll (~0x11E757, ~0x1438DA), registered at runtime |
