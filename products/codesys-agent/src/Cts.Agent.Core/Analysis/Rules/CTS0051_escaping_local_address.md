---
title: Escaping address of local value
since: 3.1.0
related: [CTS0018, CTS0028]
---

## What it is

`ADR()` takes the address of a local or temporary value, and that address is
directly returned, stored in an external or retained destination, or passed to
a call where it may be retained.

## Why it is dangerous

The local storage is valid only for the current POU invocation. A pointer that
survives the invocation can later dereference reclaimed stack storage and
produce corrupted data or an access violation.

## Example

```st bad 1
FUNCTION GetBuffer : POINTER TO BYTE
VAR_TEMP
    localByte : BYTE;
END_VAR
IMPLEMENTATION
GetBuffer := ADR(localByte); // cts:here
```

```st bad 1
FUNCTION StoreBuffer : BOOL
VAR_TEMP
    localByte : BYTE;
END_VAR
IMPLEMENTATION
StoreBuffer := StoreForLater(ADR(localByte)); // cts:here
```

## When ignoring is legitimate

- The address is consumed synchronously and the called API is documented not
  to retain it.
- The pointer is passed as the result buffer to the supported synchronous
  `SysSockSendTo` call.
- The source is generated and a target-specific transformation owns the
  address lifetime.

```st good
FUNCTION UseBuffer : BOOL
VAR_TEMP
    localByte : BYTE;
    localAddress : POINTER TO BYTE;
END_VAR
IMPLEMENTATION
localAddress := ADR(localByte);
UseBuffer := ReadNow(localAddress);
```

## How to fix

Use storage whose lifetime is owned by the receiver, a retained/static
variable with an explicitly managed lifetime, or copy the value instead of
passing its address. This rule intentionally does not follow multi-step
pointer assignments.
