---
title: Variable declaration alignment
since: 3.0.0
---

## What it is

Variable declarations in one `VAR` section and one blank-line-separated group
do not share a base indentation or an aligned `:` column.

## Why it is dangerous

This is a style issue, but a broken declaration table makes types and variable
groups harder to scan and increases the chance of reading the wrong type or
initializer during maintenance.

## Example

```st bad 1
PROGRAM P
VAR
    short_name : INT;  // cts:here
    much_longer_name: BOOL;
END_VAR
IMPLEMENTATION
END_PROGRAM
```

```st good
PROGRAM P
VAR
    short_name       : INT;
    much_longer_name : BOOL;
END_VAR
IMPLEMENTATION
END_PROGRAM
```

## When ignoring is legitimate

An intentionally separate declaration group can be separated with a blank
line. Comments and initializers are preserved and do not affect alignment.

## How to fix

Align the declaration base indentation and the `:` column within each group.
The future formatter may apply this whitespace-only change automatically.
