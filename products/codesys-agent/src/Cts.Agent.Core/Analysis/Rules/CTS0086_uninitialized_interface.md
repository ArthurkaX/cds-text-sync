---
title: Uninitialized interface use
since: 3.1.0
related: [CTS0061]
---

## What it is

`CTS0086` reports access to a project interface variable before an assignment
or non-null declaration initializer is visible in the same POU.

## Why it is dangerous

An uninitialized interface has no object behind its dispatch table. Calling a
method or reading a property can fault the task, especially during startup
before the owning function block has completed initialization.

## Example

```st bad 1
// cts:interface IMotor
PROGRAM Main
VAR
    motor : IMotor;
END_VAR

IMPLEMENTATION
motor.Start(); // motor has no assigned implementation // cts:here
```

```st good
// cts:interface IMotor
// cts:fb FB_Motor
PROGRAM Main
VAR
    motor : IMotor;
    concrete : FB_Motor;
END_VAR
IMPLEMENTATION
motor := concrete;
motor.Start();
```

## When ignoring is legitimate

Ignore only when the interface is initialized by generated code or an external
startup contract that is not present in the project view. Inputs and `VAR_IN_OUT`
parameters are intentionally excluded because their caller owns initialization.

## How to fix

Assign a concrete function block before first use, initialize the interface in
the startup path, or guard the call with the project's explicit validity
contract. Keep the initialization visible before the first access.
