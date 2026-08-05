---
title: Invalid FOR loop step
since: 3.1.0
related: [CTS0030]
---

## What it is

A `FOR` loop uses a literal `BY 0`, or a literal step whose sign moves away
from the literal `TO` boundary.

## Why it is dangerous

A zero step cannot make progress. A step in the wrong direction can produce a
loop that never reaches its boundary and may trip the watchdog.

## Example

```st bad 1
FOR i := 0 TO 10 BY 0 DO // cts:here
    Work();
END_FOR;
```

```st good
FOR i := 10 TO 0 BY -1 DO
    Work();
END_FOR;
```

## When ignoring is legitimate

- The source is generated and the loop header is replaced before deployment.
- The loop is intentionally unreachable, but it should normally be removed.

## How to fix

Use a non-zero step directed toward the `TO` boundary. Variable bounds and
steps are intentionally left to a future path-sensitive rule.
