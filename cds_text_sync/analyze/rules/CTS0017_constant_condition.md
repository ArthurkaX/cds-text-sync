---
title: Constant control-flow condition
since: 3.0.0
related: [CTS0010]
---

## What it is

An `IF`, `ELSIF`, or `WHILE` uses the literal `TRUE` or `FALSE` as its
condition.

## Why it is dangerous

Literal conditions commonly mark temporary stubs. They can leave production
behavior permanently disabled or make a branch look configurable when it is
not.

## Example

```st bad 1
PROGRAM Main
IMPLEMENTATION
IF FALSE THEN // cts:here
    StartLegacyPath();
END_IF;
```

```st good
PROGRAM Main
IMPLEMENTATION
IF EnableLegacyPath THEN
    StartLegacyPath();
END_IF;
```

## When ignoring is legitimate

- A deliberately disabled feature is retained temporarily with an issue link.
- A permanent task loop intentionally uses `WHILE TRUE` and exits internally.

## How to fix

Replace the literal with the intended condition, or remove the dead branch.
