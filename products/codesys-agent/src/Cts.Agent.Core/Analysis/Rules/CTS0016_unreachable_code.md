---
title: Unreachable code after control-flow exit
since: 3.0.0
related: [CTS0015]
---

## What it is

A statement follows `RETURN`, `EXIT`, or `CONTINUE` in the same implementation
path.

## Why it is dangerous

The following statement cannot execute. It is usually stale code left after a
refactoring or a misplaced control-flow exit.

## Example

```st bad 1
PROGRAM Main
IMPLEMENTATION
RETURN;
DoWork(); // cts:here
```

```st good
PROGRAM Main
IMPLEMENTATION
DoWork();
RETURN;
```

## When ignoring is legitimate

- The code is generated and a later tool removes the unreachable branch.
- The exit is temporary during an active debugging change.

## How to fix

Move the statement before the exit or remove the unreachable statement.
