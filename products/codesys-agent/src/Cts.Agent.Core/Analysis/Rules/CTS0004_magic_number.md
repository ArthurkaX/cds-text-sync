---
title: Magic numeric literal
since: 3.0.0
related: [CTS0002]
---

## What it is

A numeric literal outside the trivial range (by default integers from -10 to
10 and reals from -1 to 1) used at least twice in one callable implementation. Repeated thresholds, limits, delays, and offsets are often
clearer as a `VAR CONSTANT` member or as an input parameter.

## Why it is dangerous

An unnamed value hides its meaning and makes coordinated changes error-prone.
Two occurrences can drift apart when one is updated and the other is missed.

## Example

```st bad 2
PROGRAM Main
VAR
    value : INT;
END_VAR

IMPLEMENTATION

IF value > 75 THEN  // cts:here
    value := value - 75;  // cts:here
END_IF;
```

```st good
PROGRAM Main
VAR CONSTANT
    MAX_STEP : INT := 75;
END_VAR
VAR
    value : INT;
END_VAR

IMPLEMENTATION

IF value > MAX_STEP THEN
    value := value - MAX_STEP;
END_IF;
```

A literal counts by its value in any base: `16#0000` and `16#01` are as
trivial as `0` and `1`, and `16#64` repeats `100`:

```st good
PROGRAM Main
VAR
    register : WORD;
    unit : BYTE;
END_VAR

IMPLEMENTATION

register := 16#0000;
unit := 16#01;
register := 16#0000;
unit := 16#01;
```

```st bad 2
PROGRAM Main
VAR
    percent : INT;
END_VAR

IMPLEMENTATION

IF percent > 16#64 THEN  // cts:here
    percent := 100;  // cts:here
END_IF;
```

## When ignoring is legitimate

- The value is a universally understood sentinel or arithmetic identity.
- The occurrences are deliberately tied to a protocol or vendor-defined
  representation.
- The value is intentionally local and naming it would make the code less
  readable.

In those cases, suppress the finding with a nearby directive and document why
the literal should remain inline.

## How to fix

Give the value a domain-specific name in `VAR CONSTANT`, or expose it as an
input parameter when it is part of the unit's configuration. Replace all
repeated occurrences with that name.
