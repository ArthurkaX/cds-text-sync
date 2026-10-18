---
title: Variable declaration alignment
since: 3.0.0
---

## What it is

Variable declarations in one `VAR` section and one blank-line-separated group
do not share a base indentation or an aligned `:` column. Columns are counted
as the CODESYS editor shows them, a tab reaching the next multiple of four, so
a table aligned with tabs is aligned.

## Why it is dangerous

This is a style issue, but a broken declaration table makes types and variable
groups harder to scan and increases the chance of reading the wrong type or
initializer during maintenance.

## Example

```st bad 2
PROGRAM P
VAR
    short_name : INT;  // cts:here
    much_longer_name: BOOL;  // cts:here
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

```st good
PROGRAM P
VAR
	count		: INT;
	next_state	: INT;
END_VAR
IMPLEMENTATION
END_PROGRAM
```

## When ignoring is legitimate

An intentionally separate declaration group can be separated with a blank
line. Comments and initializers are preserved and do not affect alignment.

## How to fix

Align the declaration base indentation and the `:` column within each group;
`cts fmt` makes this whitespace-only change.
