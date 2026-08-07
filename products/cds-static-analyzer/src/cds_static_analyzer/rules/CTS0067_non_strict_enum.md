---
title: Non-strict enumeration
since: 3.1.0
related: [CTS0059]
---

# Non-strict enumeration

## What it is

Detects an enumeration declaration without the `strict` attribute.

## Why it is dangerous

Non-strict enumerations permit accidental numeric assignments.

Reports an enumeration without CODESYS' `strict` attribute. Strict
enumerations prevent accidental numeric assignments and comparisons.

```st bad 1
TYPE State : (Idle, Running); END_TYPE // cts:here
```

## Example

```st good
{attribute 'strict'}
TYPE State : (Idle, Running); END_TYPE // cts:here
```

## When ignoring is legitimate

Compatibility with an external non-strict interface may require it.

## How to fix

Add `{attribute 'strict'}` immediately before the `TYPE` declaration.
