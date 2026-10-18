---
title: Duplicate IF condition
since: 3.1.0
related: [CTS0016, CTS0017]
---

## What it is

An `IF/ELSIF` chain contains the same condition more than once, or a
condition over boolean variables that can only hold when an earlier one of
the chain does (`ELSIF Ready AND Fault` after `IF Ready`). A comparison in an
earlier condition counts as never holding; a call in any condition up to the
arm leaves it out, since the call may change what the later one reads.

## Why it is dangerous

After the first matching branch, a repeated `ELSIF` condition can never be
selected. This is commonly caused by copy-paste or an incomplete edit.

## Example

```st bad 1
IF Ready THEN
    Start();
ELSIF Ready THEN // cts:here
    Retry();
END_IF;
```

```st bad 1
IF Ready THEN
    Start();
ELSIF NOT Fault THEN
    Wait();
ELSIF Ready AND Fault THEN // cts:here
    Retry();
END_IF;
```

```st good
IF Ready THEN
    Start();
ELSIF Fault THEN
    Retry();
END_IF;
```

```st good
IF Ready AND Fault THEN
    Retry();
ELSIF Ready THEN
    Start();
ELSIF Count > 3 THEN
    Stop();
ELSIF Count > 3 OR Fault THEN
    Reset();
END_IF;
```

## When ignoring is legitimate

- Generated code intentionally repeats a condition for a target-specific
  transformation.
- The duplicate branch is temporary during an incomplete refactoring.

## How to fix

Remove the redundant branch or replace its condition with the intended one.
