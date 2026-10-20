---
title: Documentation comment after a declaration
related: [CTS0073]
---

## What it is

`CTS0101` reports a `///` comment that follows a declaration on the same
line, such as `xFall : BOOL; /// TRUE -> FALSE`.

## Why it is dangerous

CODESYS takes a `///` comment as the documentation of the declaration
*below* it. The variable on the comment's line shows no comment in the
Library Manager, the input assistant and `cts docs`, and the next variable
shows this one. A review reads the line as documented and misses the shift.

## Example

```st bad 2
FUNCTION_BLOCK FB_Edge
VAR_INPUT
    xIn : BOOL; /// The signal watched // cts:here
END_VAR
VAR_OUTPUT
    xRise : BOOL; /// FALSE -> TRUE // cts:here
    xFall : BOOL;
END_VAR
IMPLEMENTATION
xRise := xIn;
xFall := NOT xIn;
```

```st good
FUNCTION_BLOCK FB_Edge
VAR_INPUT
    /// The signal watched
    xIn : BOOL;
END_VAR
VAR_OUTPUT
    xRise : BOOL; // FALSE -> TRUE
    /// TRUE -> FALSE
    xFall : BOOL;
END_VAR
IMPLEMENTATION
xRise := xIn;
xFall := NOT xIn;
```

## When ignoring is legitimate

Hardly ever: the comment documents a declaration it does not stand beside.
When the next declaration is meant, move the comment above it.

## How to fix

Put the `///` comment on the line above its declaration, or write `//` for a
comment that belongs to the line it is on.
