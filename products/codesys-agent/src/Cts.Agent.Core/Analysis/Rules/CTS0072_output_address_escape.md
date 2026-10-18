---
title: Escaping address of VAR_OUTPUT
since: 3.1.0
related: [CTS0051, CTS0060]
---

## What it is

`ADR()` is used on a `VAR_OUTPUT` value. This creates a pointer alias to a
value that is part of the POU interface rather than passing the value itself.

## Why it is dangerous

The pointer can be stored or passed to another component, allowing code to
modify the output outside the POU call. The alias is easy to miss during code
review and can outlive the operation that produced the output.

## Example

```st bad 1
FUNCTION_BLOCK Producer
VAR_OUTPUT
    Value : INT;
END_VAR
IMPLEMENTATION
SendLater(ADR(Value)); // cts:here
```

```st good
FUNCTION_BLOCK Producer
VAR_OUTPUT
    Value : INT;
END_VAR
IMPLEMENTATION
SendLater(Value);
```

## When ignoring is legitimate

- A tightly scoped library API explicitly requires the address and guarantees
  that it is consumed before the POU returns.
- The code is generated integration code with a documented lifetime contract.

## How to fix

Pass the output value by value or copy it into storage whose lifetime is
explicitly managed by the receiving component. If an address is unavoidable,
document and enforce that it cannot escape the current call.
