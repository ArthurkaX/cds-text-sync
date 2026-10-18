---
title: Mixed AND and OR without parentheses
since: 3.1.0
related: [CTS0010, CTS0081]
---

## What it is

`CTS0098` reports a boolean expression that mixes `AND` and `OR` without
parentheses. The expression is read whole, however its lines are broken (as
`cts fmt` breaks a long `IF` condition), and each parenthesized group and each
call argument is read on its own: `(a AND b) OR c` is grouped, `(a) OR b AND c`
is not.

## Why it is dangerous

The language precedence may be correct while the expression is still easy to
misread during commissioning or maintenance. A later edit can change one
operator and silently change which conditions are grouped together.

## Example

```st bad 1
IF AutoMode AND Ready OR ForceStart THEN // cts:here
    Start := TRUE;
END_IF;
```

```st good
IF (AutoMode AND Ready) OR ForceStart THEN
    Start := TRUE;
END_IF;
```

## When ignoring is legitimate

Ignore only when the project coding standard explicitly documents the intended
operator precedence. An expression whose every group has one kind of operator
is not reported.

## How to fix

Add parentheses around each intended boolean group and keep the condition on a
readable line or extract the groups into named boolean variables.
