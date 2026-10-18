---
title: Unsafe enumeration use
since: 3.1.0
related: [CTS0003, CTS0015, CTS0044]
---

## What it is

An enumeration variable is assigned a value that is not declared by its enum,
or an enum-based `CASE` omits members without an `ELSE` branch.

## Why it is dangerous

The state machine can enter a value with no defined behaviour. An incomplete
`CASE` may silently leave outputs and state unchanged when a new enum member
is added later.

## Example

```st bad 2
TYPE State : (Idle, Running, Error); END_TYPE
PROGRAM Main
VAR
    state : State;
END_VAR
IMPLEMENTATION
state := 42; // cts:here
CASE state OF // cts:here
    Idle: HandleIdle();
    Running: HandleRunning();
END_CASE;
END_PROGRAM
```

```st bad 2
TYPE State : (Idle, Running, Error); END_TYPE
PROGRAM Main
VAR
    state : State;
END_VAR
IMPLEMENTATION
state := State.Stopped; // cts:here
state := Stopped; // cts:here
END_PROGRAM
```

A member's value may be a based literal; the members after it count on from
it:

```st good
TYPE Code : (Ready := 16#10, Busy, Failed := 2#100000); END_TYPE
PROGRAM Main
VAR
    code : Code;
END_VAR
IMPLEMENTATION
code := 17;
code := 32;
END_PROGRAM
```

A variable of the enum's type, in a GVL or the owning function block, and an
expression are values the compiler checks, not members:

```st good
TYPE State : (Idle, Running, Error); END_TYPE
PROGRAM Main
VAR
    state : State;
END_VAR
IMPLEMENTATION
state := GVL_Plant.requested; // cts:gvl GVL_Plant: requested State
state := requested;
state := State.Running;
state := NextState(state);
END_PROGRAM
```

```st good
CASE state OF
    Idle: HandleIdle();
    Running: HandleRunning();
    Error: HandleError();
ELSE
    HandleUnknown();
END_CASE;
```

## When ignoring is legitimate

- The enum is intentionally used as a wire-format integer and the conversion
  is validated at the protocol boundary.
- The `CASE` is deliberately partial and leaving the previous state unchanged
  is the documented default behaviour.

## How to fix

Assign only declared enum members and add the missing branches or an explicit
`ELSE` policy to the `CASE` statement.
