---
title: Suspicious STRING operation
---

## What it is

Reports simple operations on `STRING` values that depend on the configured
single-byte encoding: character indexing, taking an address, and assigning a
non-ASCII literal.

## Why it is dangerous

The result can change when the project encoding option changes. A character
may occupy more than one byte, while indexing and address arithmetic operate
on bytes.

## Example

```st bad 3
FUNCTION Inspect : BOOL
VAR
    Text : STRING(80);
    Code : BYTE;
END_VAR
IMPLEMENTATION
Code := Text[2]; // cts:here
ADR(Text); // cts:here
Text := 'Ä'; // cts:here
Inspect := TRUE;
```

```st good
FUNCTION Build : STRING
VAR_INPUT
    Part : STRING;
END_VAR
IMPLEMENTATION
Build := CONCAT('A', Part);
```

## When ignoring is legitimate

- The project explicitly uses a single-byte encoding and the byte-level access
  is intentional.
- The string is an external protocol buffer with a documented encoding.

## How to fix

Use encoding-aware string operations or a project-wide string type and avoid
assuming that a character occupies exactly one byte.
