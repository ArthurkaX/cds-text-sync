# CODESYS Visualization XML -- Format Overview

> **Note for `cts visu` users:** This reference documents the raw CODESYS
> IArchivable XML serialization format. The `cts visu` tool generates correctly
> structured XML for supported types. Use this overview when hand-authoring XML
> for types not yet in the catalog, or to understand the generated output.

CODESYS visualization files are **not hand-authored XML**. They are the
`IArchivable` serialization that the CODESYS IDE visual editor reads and writes
when it round-trips a visualization object. To be accepted, generated XML must
match the shape the editor produces. This skill encodes that shape, verified
against real extracted elements (the *ground truth*), not guesswork.

> If a structural detail here disagrees with anything you remember, trust the
> ground-truth `examples/` and these references.

## The element block

Every visual element is one `<Single>` block typed with the **element GUID**:

```xml
<Single Type="{f86c2928-8614-4cca-824b-e819ac4d58c4}" Method="IArchivable">
  <Array Name="ConfiguredComplexInputs" Type="{1de566f6-72a7-494c-9353-9a418172c96e}" />
  <List Name="Elements" Type="System.Collections.ArrayList" />
  <Null Name="VisualElementDescription" />
  <Single Name="VisualElemMemberList" Type="{17e26cd1-bb9b-47fe-a3d5-18fcd63b9c96}" Method="IArchivable">
    <List Name="VisualElemMemberList" Type="{a4b83bea-3742-489c-9fe8-d96d68dba7ab}">
      <!-- property members, see below -->
    </List>
  </Single>
  <Single Name="VisualElementName" Type="string">Button</Single>
  <Single Name="VisualElementTypeName" Type="string">VisuFbElemButton</Single>
  <Single Name="VisualElementIsRectangle" Type="bool">True</Single>
  <Single Name="VisualElementIdentifier" Type="string">GenElemInst_1</Single>
  <Null Name="VisualElementOfflinePaintCommands" />
  <Null Name="VisualElementFrameInformation" />
  <Dictionary Type="System.Collections.Hashtable" Name="VisualElementInputActions" />
  <Single Name="VisualElementIdentification" Type="System.Guid">...</Single>
  <Single Name="VisualElementOwningObjectGuid" Type="System.Guid">...</Single>
  <Array Name="LMGuids" Type="System.Guid" />
  <Dictionary Type="System.Collections.Hashtable" Name="SubElements" />
  <Single Name="VisualElementId" Type="int">0</Single>
  <List Name="UserManagementAccessRights" Type="System.Collections.ArrayList" />
  <Single Name="AnimationDuration" Type="string">0</Single>
  <Single Name="BringToForeground" Type="string" />
  <Single Name="ElementVersion" Type="byte">0</Single>
  <Null Name="TabOrder" />
</Single>
```

> **Member-list wrapper (mandatory).** Real CODESYS IDE output wraps the
> `VisualElemMemberList` `<List>` in an outer `<Single Name="VisualElemMemberList"
> Type="{17e26cd1-...}" Method="IArchivable">`. This is the **only** accepted
> form. All examples use the wrapped form. The wrapper must appear at position 4
> (after `ConfiguredComplexInputs`, `Elements`, `VisualElementDescription`) and
> before `VisualElementName`.

Elements live inside `<List Name="VisualElementList">` in a real screen file.

### Mandatory element fields

- `ConfiguredComplexInputs` (Array) -- must appear at position 0.
- `Elements` (List) -- must appear at position 1.
- `VisualElementDescription` (Null) -- must appear at position 2.
- `VisualElemMemberList` -- the property bag (must be the wrapped `Single`,
  not the bare `List`).
- `VisualElementName` (string) -- display name.
- `VisualElementTypeName` (string) -- one of the catalog types (`VisuFbElem...`).
- `VisualElementIdentifier` (string) -- `GenElemInst_<N>`, **unique per file**.

`VisualElementIdentification` / `VisualElementOwningObjectGuid` are `System.Guid`
values; in examples they are anonymized placeholders. The IDE assigns real GUIDs
on import -- when authoring new elements you may leave the placeholder GUIDs.

## The property member

Inside `VisualElemMemberList`, **every property** is wrapped in a member block
typed with the **property-member GUID**, carrying an `Id` (hash code, `long`) and
a `Value`:

```xml
<Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">
  <Single Name="Id" Type="long">1649127785</Single>   <!-- X position -->
  <Single Name="Value" Type="int">100</Single>
</Single>
```

- `Id` is a **fixed hash code** for the property name -- never invent one. Look it
  up in [property-ids.md](property-ids.md).
- `Value` may be a scalar (`<Single Name="Value" Type="int|short|uint|string|bool">`)
  or a structured `<List Name="Value" ...>` (fonts, color lists -- see
  [colors-and-fonts.md](colors-and-fonts.md)).

> Common mistake: writing `<Single Id="1649127785">...` directly. That is **wrong**.
> The property is always the `{c694e3a2...}` member with `Id` and `Value` children.

## Coordinate system

Integer pixels, origin top-left, Y grows downward. Rectangular elements use:

| Property | Id | Meaning |
|----------|-----|---------|
| X (Left) | `1649127785` | left edge |
| Y (Top)  | `357335551`  | top edge |
| Width    | `2422045748` | width |
| Height   | `2134141914` | height |

`Width`/`Height` appear as either `int` or `short` in the wild; both are accepted.
`VisuFbElemLine`, `VisuFbElemPolygon`, and `VisuFbElemPie` are **not** rectangles
(`VisualElementIsRectangle=False`) and use point lists instead -- see
[element-catalog.md](element-catalog.md).

## Value types seen

`int`, `short`, `uint`, `long` (Ids only), `bool` (`True`/`False`), `string`,
`byte`, `double`, `ushort`, `System.Guid`. Empty strings are written
`<Single Name="Value" Type="string" />`.

## Key GUIDs (the skeleton)

| GUID | Role |
|------|------|
| `f86c2928-8614-4cca-824b-e819ac4d58c4` | visual element block |
| `a4b83bea-3742-489c-9fe8-d96d68dba7ab` | `VisualElemMemberList` |
| `c694e3a2-5c0b-4177-ab35-cb06bd5a6a02` | property member (Id + Value) |
| `fa491db2-51ff-4bc1-9cd0-ce8c94ff6216` | color struct |
| `9e842eb2-1463-4af2-b605-4fbb17044f94` | font descriptor |
| `69265815-ba9d-4bec-bfcb-427fb9172844` | input-action array |
| `6302d3fe-6ea5-4c42-819a-a9734a133b3d` | ST-snippet action |
| `e8e7e747-f76f-4dee-ab1c-b9637e41ac26` | InputBox action |
| `5d84b30d-2b79-4065-9de4-596597fc09b4` | Dialog-open action |
| `17e26cd1-bb9b-47fe-a3d5-18fcd63b9c96` | `VisualElemMemberList` wrapper |
| `1de566f6-72a7-494c-9353-9a418172c96e` | `ConfiguredComplexInputs` array |
| `16f3f59a-37ad-4991-a1af-cc2926974e08` | DialogPosition enum (InputBox action) |

### Screen-level structs

The IDE wraps every visualization file in an `IArchivable` container
(MetaObject / VisuManager / etc.). These GUIDs never appear inside a visual
element:

| GUID | Role |
|------|------|
| `6198ad31-4b98-445c-927f-3258a0e82fe3` | visualization root |
| `81297157-7ec9-45ce-845e-84cab2b88ade` | MetaObject |
| `2c41fa04-1834-41c1-816e-303c7aa2c05b` | Properties dictionary |
| `829a18f2-c514-4f6e-9634-1df173429203` | property-entry value type |
| `fa2ee218-a39b-4b6d-b249-49dbddbd168a` | ParentObjects dictionary |
| `477d844b-9b2a-407e-90a4-d36fd6dde2fc` | visu properties block |
| `34718b76-91f6-43de-8c65-b77e0b1ee621` | VisuSizeMode enum |
| `f18bec89-9fef-401d-9953-2f11739a6808` | VisuManager object |
| `f285c9a3-7019-446b-b98c-ccec3a0af8fa` | VisualElemList |
| `ef9d0b20-c96e-48db-b361-2ded4063150e` | VisualElementList list type |
| `1038f12c-dd4b-4f96-87a3-a350fe8f3552` | Background |
| `703465dc-4679-4ff2-bcc3-c57d0a204da3` | GeneratedLMMDescriptions |
| `40d6dd8d-dfd0-493a-8e29-c9a35e1e6539` | GeneratedVisuFbDescription |
| `7df88604-7ac5-4e36-91c4-55e4fdad3e68` | FbMethods dictionary |
| `f3878285-8e4f-490b-bb1b-9acbb7eb04db` | TextDocument |
| `6b108d46-58af-4e41-a3f4-174d8f160cc4` | Hotkeys |
| `5f612b0e-b404-455f-8177-27864e9f5332` | VisuSizeManager |
| `6ad3e88f-aee2-4766-a7ea-a8790037ef51` | VisuSizeManager Size entry |

## Authoring workflow (hand-authoring XML)

1. Pick the element type in [element-catalog.md](element-catalog.md).
2. Look up each property `Id` in [property-ids.md](property-ids.md); copy a matching
   file from `examples/` as your structural template.
3. Fill geometry, colors ([colors-and-fonts.md](colors-and-fonts.md)), and any
   input action ([input-actions.md](input-actions.md)).
4. Validate: check each color structs `CanonicalName` is non-empty, and that
   text/Text-ID invariants hold (see [element-catalog.md](element-catalog.md)).
