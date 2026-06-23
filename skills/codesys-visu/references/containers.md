# Containers: Frames, Groups, Tables

> **Note for `cts visu` users:** The `cts visu` tool does NOT yet support
> containers (frames, groups, tables). Use this reference when hand-authoring
> XML for these element types.

Three element families hold or reference other content rather than drawing a
single primitive.

## VisuFbFrame -- embedded sub-visualization

A frame element references another visualization object. Instead of the usual
`<Null Name="VisualElementFrameInformation" />`, it carries a populated
`VisualElementFrameInformation`:

```xml
<Single Name="VisualElementFrameInformation" Type="{7fd6515d-f891-4717-b53f-b14197c6706c}" Method="IArchivable">
  <List Name="ContainedGuids" Type="System.Collections.ArrayList" />
  <List Name="ContainedVisualizations" Type="System.Collections.ArrayList" />
  <Array Name="ContainedVisualizations33" Type="string">
    <Single Type="string">FRAME_NAME</Single>
  </Array>
</Single>
```

`FRAME_NAME` is the name of the referenced visualization. Multiple entries in the
array stack several referenced visualizations (the IDE switches between them by
index). Keep the `33` suffix on `ContainedVisualizations33`. The two preceding
lists (`ContainedGuids`, `ContainedVisualizations`) are present but empty in real
output.

> The frame-info type GUID is `{7fd6515d-f891-4717-b53f-b14197c6706c}` (full GUID
> verified against `_Basic.xml`). The referenced visu also appears as a
> `2473092364` reference-value member inside the element's `VisualElemMemberList`
> (with the `363316305` `VisuStructReferenceList` type descriptor) -- see
> [element-catalog.md](element-catalog.md).

## VisuFbGroup / VisuFbGroupBox -- child elements

Group containers hold their child elements in the element's `SubElements`
dictionary (normally `<Dictionary ... Name="SubElements" />` when empty). Each
child is keyed and its value is a nested element block following the same
`{f86c2928-...}` skeleton. Geometry on the group is the bounding box; children use
coordinates relative to the visualization, not the group.

`VisuFbGroupBox` additionally draws a titled frame around the grouped area; its
title text is in property `390574330`.

## VisuFbElemTable -- columns via SubElements

A table stores its column templates in `SubElements`, keyed
`Columns.Column.[N].Template`:

```xml
<Dictionary Type="System.Collections.Hashtable" Name="SubElements">
  <Entry>
    <Key>
      <Single Type="string">Columns.Column.[0].Template</Single>
    </Key>
    <Value>
      <!-- a nested element block describing the cell template for column 0 -->
    </Value>
  </Entry>
</Dictionary>
```

The table element's own member list carries layout flags and the data-array
variable; per-column rendering is defined by the nested template elements. Copy
an existing table example as a whole when building a table rather than assembling
columns by hand -- the nesting is intricate and easy to get subtly wrong.

## General nesting rule

Whenever a container holds another visual element, that inner element is a
complete `{f86c2928-...}` block with its own `VisualElemMemberList` and identity
fields.
