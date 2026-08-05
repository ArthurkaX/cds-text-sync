---
title: Magic numeric literal
since: 3.0.0
related: [CTS0002]
---

## What it is

A non-trivial numeric literal used at least twice in one callable
implementation. Repeated thresholds, limits, delays, and offsets are often
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
