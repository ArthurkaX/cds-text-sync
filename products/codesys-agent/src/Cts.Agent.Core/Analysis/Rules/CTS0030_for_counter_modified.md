---
title: Modifying a FOR loop control variable inside the loop
---

## What it is

Reports a direct assignment to a `FOR` loop's control variable from inside the
loop body.

## Why it is dangerous

The loop updates its control variable automatically. Changing it in the body
can skip iterations, change the termination point, or make the loop's behavior
hard to understand.

## Example

```st bad 1
FOR i := 0 TO 10 DO
    value := Values[i];
    IF value = 0 THEN
        i := i + 1; // cts:here
    END_IF;
END_FOR;
```

```st good
FOR i := 0 TO 10 DO
    value := Values[i];
    IF value <> 0 THEN
        Process(value);
    END_IF;
END_FOR;
```

## What is intentionally ignored

Reading the counter is normal and is not reported. Named call arguments such
as `Timer(IN := TRUE)` are not assignments to a loop counter.

## When ignoring is legitimate

The counter is changed deliberately and the resulting loop behavior is part
of the design. In that case, document the intent or suppress the finding.

## How to fix

Use a separate variable for additional state or filtering. Let the `FOR`
statement control its own counter.
