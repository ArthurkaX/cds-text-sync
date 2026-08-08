---
title: Structural indentation
since: 3.0.0
---

## What it is

The indentation of an ST implementation does not match its actual block
nestedness, or tabs and spaces are mixed in one leading prefix.

Declaration sections are intentionally not checked here. Their table-like
alignment belongs to a separate future rule.

The model is block-local: the outermost expected indent is *learned* from the
first implementation line, and each block indents its body by one uniform
step. This means a whole body uniformly shifted one level is not drift, and
each `CASE` block keeps whichever label style it chose, provided its own
labels and statements stay consistent.

## Why it is dangerous

This is a style issue rather than a runtime fault, but misleading indentation
can hide the real scope of a statement and make maintenance errors likely.

## Why it matters

ST does not use indentation as syntax, but inconsistent historical indentation
can make a flat statement look nested—or hide a real nesting error. This is
especially misleading when reading ST with experience from Python.

## Example

```st bad 1
PROGRAM P
IMPLEMENTATION
IF ready THEN
    FOR i := 1 TO 10 DO
        value := i;
            total := total + value;  // cts:here
    END_FOR
END_IF;
```

```st good
PROGRAM P
IMPLEMENTATION
IF ready THEN
    FOR i := 1 TO 10 DO
        value := i;
        total := total + value;
    END_FOR
END_IF;
```

```st good
PROGRAM P
IMPLEMENTATION
CASE step OF
    1:
        value := 1;
    2:
        value := 2;
END_CASE;
```

```st good
PROGRAM P
IMPLEMENTATION
CASE step OF
1:
    value := 1;
2:
    value := 2;
END_CASE;
```

```st good
PROGRAM P
IMPLEMENTATION
    IF ready THEN
        value := 1;
    END_IF;
```

```st bad 1
PROGRAM P
IMPLEMENTATION
CASE step OF
1:
    value := 1;
    2:  // cts:here
END_CASE;
```

The last block flags the indented label: a `CASE` block fixes its label column
from its first label, so a second label that disagrees is drift. A statement
one level below an indented label would be flagged for the same reason; here
the second branch is left empty so only the label itself is reported.

## When ignoring is legitimate

Continuation lines may be aligned for readability and are not required to
match block indentation. Declaration-table alignment is also handled by a
separate rule.

## How to fix

Align each statement with its real `IF`, `FOR`, `CASE`, `WHILE`, or `REPEAT`
block level. Keep continuation-line alignment separate from block indentation.
