---
title: String assignment may truncate the destination
since: 3.1.0
related: [CTS0028, CTS0078]
---

## What it is

An explicitly bounded `STRING(source_size)` is assigned to a smaller
`STRING(destination_size)`.

## Why it is dangerous

The source can contain more characters than the destination can store. The
assignment may therefore discard the tail of a message, path, identifier, or
protocol field without making that loss obvious at the call site.

## Example

```st bad 1
PROGRAM Main
VAR
    source : STRING(80);
    target : STRING(20);
END_VAR
IMPLEMENTATION
target := source; // cts:here
END_PROGRAM
```

```st good
PROGRAM Main
VAR
    source : STRING(20);
    target : STRING(20);
END_VAR
IMPLEMENTATION
target := source;
END_PROGRAM
```

## When ignoring is legitimate

- The destination is a deliberately shortened protocol field.
- The source is constrained elsewhere before the assignment, but that range is
  not visible to this local rule.
- A library or generated interface defines truncation as its contract.

## How to fix

Make both declarations match, validate the source length before assignment, or
perform an explicit and documented truncation at the protocol boundary.
