# Input Actions

> **Note for `cts visu` users:** The `cts visu` tool does NOT yet support
> input actions (click handlers, InputBox, etc.). Use this reference when
> hand-authoring XML for interactive elements.

Interactive behavior lives in the element's
`<Dictionary Name="VisualElementInputActions">`. The dictionary is keyed by an
**event name** (a `<Single Type="string">`); the value is an
`<Array Type="{69265815-ba9d-4bec-bfcb-427fb9172844}">` holding one or more
**action** structs. When an element has no interaction, the dictionary is empty:

```xml
<Dictionary Type="System.Collections.Hashtable" Name="VisualElementInputActions" />
```

## Event names

`OnMouseClick` is by far the most common (verified). The IDE also emits
`OnMouseDown`, `OnMouseUp`, `OnMouseEnter`, `OnMouseLeave`, `OnDialogClosed`.
Use `OnMouseClick` unless you specifically need press/release semantics.

## Action skeleton

```xml
<Dictionary Type="System.Collections.Hashtable" Name="VisualElementInputActions">
  <Entry>
    <Key>
      <Single Type="string">OnMouseClick</Single>
    </Key>
    <Value>
      <Array Type="{69265815-ba9d-4bec-bfcb-427fb9172844}">
        <!-- one or more action structs go here -->
      </Array>
    </Value>
  </Entry>
</Dictionary>
```

## 1. ST snippet -- `{6302d3fe-6ea5-4c42-819a-a9734a133b3d}`

Runs inline Structured Text on the event. The body is raw ST, not an expression:

```xml
<Single Type="{6302d3fe-6ea5-4c42-819a-a9734a133b3d}" Method="IArchivable">
  <Single Name="STSnippet" Type="string">Application.PLC_VAR := NOT Application.PLC_VAR;</Single>
</Single>
```

Used by buttons and clickable shapes (`VisuFbElemSimple`).

## 2. InputBox -- `{e8e7e747-f76f-4dee-ab1c-b9637e41ac26}`

Opens a numpad/keypad dialog to write a variable. Used by textfields and spin
controls:

```xml
<Single Type="{e8e7e747-f76f-4dee-ab1c-b9637e41ac26}" Method="IArchivable">
  <Single Name="InputBoxVariable" Type="string">Application.PLC_VAR</Single>
  <Single Name="InputType" Type="string">VisuDialogs.Numpad</Single>
  <Single Name="InputBoxMin" Type="string">1</Single>
  <Single Name="InputBoxMax" Type="string">215</Single>
</Single>
```

`InputType` is typically `VisuDialogs.Numpad` (numeric) or `VisuDialogs.Keypad`
(text). `InputBoxMin`/`InputBoxMax` bound numeric entry.

## 3. Dialog open -- `{5d84b30d-2b79-4065-9de4-596597fc09b4}`

Opens a named dialog visualization:

```xml
<Single Type="{5d84b30d-2b79-4065-9de4-596597fc09b4}" Method="IArchivable">
  <Single Name="Dialog33" Type="string">DIALOG_NAME</Single>
  <Single Name="Result" Type="string">OK</Single>
</Single>
```

`Dialog33` names the dialog object; `Result` is the result mapping
(`OK`, `Cancel`, `Yes`, `No`).

> The `33` suffix on `Dialog33` (and `ContainedVisualizations33`, see
> [containers.md](containers.md)) is part of the serialization name -- keep it.

## Combining

Multiple action structs may sit in one event's `<Array>`; they run in order.
A single element can register actions on several events by adding more `<Entry>`
items to the dictionary.
