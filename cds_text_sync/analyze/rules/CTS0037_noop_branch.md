---
title: No-op control-flow branch
since: 3.1.0
related: [CTS0023]
---

## What it is

An `IF`, `ELSIF`, `ELSE` or `CASE` branch contains only a standalone `;`.
The statement is syntactically valid but has no runtime effect.

## Why it is dangerous

This often remains after a skeleton or temporary stub was implemented and can
hide an unhandled state, especially in a `CASE ELSE` branch.

## Example

```st bad 1
CASE State OF
    Ready: Start();
ELSE
    ; // cts:here
END_CASE;
```

```st good
CASE State OF
    Ready: Start();
ELSE
    ReportUnexpectedState();
END_CASE;
```

## When ignoring is legitimate

- A deliberate no-op branch is required by a generated state machine.
- The branch is a documented placeholder during an active implementation.

## How to fix

Implement the branch, remove it, or add an explicit comment explaining why the
state is intentionally ignored.
