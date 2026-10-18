---
title: Zero timer preset time
since: 3.1.0
related: [CTS0031]
---

## What it is

A `TON`, `TOF` or `TP` function block is called with `PT := T#0...`.

## Why it is dangerous

A zero preset can make timer output change immediately and often indicates an
unfinished configuration or a unit mismatch.

## Example

```st bad 1
VAR
    T : TON;
END_VAR
T(PT := T#0s); // cts:here
```

```st good
T(PT := T#100ms);
```

## When ignoring is legitimate

- Immediate timer behaviour is explicitly required by the state machine.
- The value is used only in a test or commissioning configuration.

## How to fix

Use the intended non-zero preset or document why immediate behaviour is
required.
