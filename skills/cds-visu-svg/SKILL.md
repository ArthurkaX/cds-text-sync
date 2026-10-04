---
name: cds-visu-svg
description: >-
  Generate SVG sketches for CODESYS visualization, conforming to the
  `cts visu from-svg` schema. Use when the user wants to create,
  modify, or debug SVG files that compile into CODESYS HMI screens.
disable-model-invocation: true
---

# cds-visu-svg — SVG → CODESYS visu transpiler

The authoring contract ships inside the package, version-matched with the `cts`
CLI that compiles the sketch. Read it with:

```sh
cts guide visu-svg                                        # the contract
cts guide visu-svg --file examples/pid-schematic.svg      # lint-clean example
cts guide visu-svg --file examples/status-panel.svg       # lint-clean example
cts guide visu-svg --file advanced-elements.md            # lamp, frame, dialogs, ...
```

Generate valid SVG, render the preview and show it for approval, then compile
it with `cts visu from-svg` only after the user approves. The guide carries the
layout rules, the colour classes, the element vocabulary, and the ordered
workflow with the approval pause — read it before drawing.
