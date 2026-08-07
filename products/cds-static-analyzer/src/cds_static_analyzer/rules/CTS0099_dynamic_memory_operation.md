---
title: Dynamic memory operation
since: 3.1.0
related: [CTS0060, CTS0064]
---

## What it is

`CTS0099` reports `__NEW` and `__DELETE` in executable Structured Text. The
rule does not assume that the POU is definitely called by a cyclic task; it
reports the operation so that its execution context can be reviewed.

## Why it is dangerous

Heap allocation and release can take variable time and can fragment the
available memory. In a cyclic PLC task, that may create scan-time jitter,
allocation failures, or a watchdog trip. Repeated allocation can also hide a
leak when a pointer is overwritten before it is released.

## Example

```st bad 2
FUNCTION_BLOCK FB_Buffer
VAR
    pData : POINTER TO BYTE;
END_VAR
IMPLEMENTATION
pData := __NEW(BYTE, 1024); // allocation has unbounded cycle cost // cts:here
IF Reset THEN
    __DELETE(pData); // cts:here
END_IF;
```

```st good
FUNCTION_BLOCK FB_Buffer
VAR CONSTANT
    BufferSize : UDINT := 1024;
END_VAR
VAR
    data : ARRAY[0..1023] OF BYTE;
END_VAR
IMPLEMENTATION
data[0] := 0;
```

## When ignoring is legitimate

Ignore the finding when the POU runs only during a controlled startup or
shutdown phase, or when the target runtime documents a bounded allocator and
the allocation rate is deliberately limited. Keep the allocation paired with
an explicit release and document the execution context.

## How to fix

Prefer statically allocated buffers or preallocate objects during startup.
When dynamic memory is required, allocate outside the cyclic path, check the
returned pointer, release it exactly once, and make the ownership and lifetime
explicit.
