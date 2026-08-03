---
title: Declared symbol not referenced
since: 3.0.0
related: [CTS0002, CTS0009, CTS0011]
---

## What it is

A local or global variable is declared, but no explicit reference to it is
found in the analyzed Structured Text sources.

Local `VAR`, `VAR_TEMP`, and `VAR_STAT` members are checked in their own POU
and in the implementation bodies of its owned methods/actions/properties.
`VAR_GLOBAL` members are checked across the visible project sources.

## Why it is dangerous

This identifies likely forgotten declarations and names left behind after a
refactoring. It is a review candidate, not proof that the symbol can be
deleted: inheritance, visualization bindings, external access, generated code,
and historical interfaces may use a symbol outside the analyzed ST.

## Example

```st bad 1
PROGRAM P
VAR
    forgotten : INT;  // cts:here
    result : INT;
END_VAR
IMPLEMENTATION
result := 1;
END_PROGRAM
```

```st good
PROGRAM P
VAR
    result : INT;
END_VAR
IMPLEMENTATION
result := 1;
END_PROGRAM
```

## Excluded names

Technical placeholder components named `spare`, `dummy`, `reserved`, `unused`,
`padding`, or `filler` are ignored, including names such as `spare_1`.
Interface members (`VAR_INPUT`, `VAR_OUTPUT`, and `VAR_IN_OUT`) are covered by
more specific rules and are not reported here.

## When ignoring is legitimate

- The symbol is part of an inherited, external, visualization, or generated
  interface.
- The project uses the declaration as a historical compatibility placeholder.
- The relevant consumer is outside the analyzed project-view sources.

## How to fix

Confirm that the symbol is not part of an inherited, external, visualization,
or generated interface. Then remove the declaration or add the missing use.
