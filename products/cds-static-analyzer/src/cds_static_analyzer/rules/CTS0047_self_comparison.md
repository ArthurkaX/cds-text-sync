---
title: Self-comparison
since: 3.0.0
related: [CTS0017, CTS0021]
---

## What it is

A simple variable or qualified field is compared with itself. Equality,
`<=`, and `>=` are always true; inequality, `<`, and `>` are always false
under ordinary scalar comparison semantics.

The rule intentionally ignores calls, array/index expressions, and other
complex operands whose evaluation or type semantics need deeper analysis.

## Why it is dangerous

The expression does not compare two independent values. In a control-flow
condition it can make a branch permanently selected or permanently skipped,
which often indicates a typo or a copy-and-paste error.

## Example

```st bad 2
IF value = value THEN // cts:here
    Accept();
END_IF;
IF status <> status THEN
    Reject();
END_IF;
```

```st good
IF value = expected_value THEN
    Accept();
END_IF;
IF status <> previous_status THEN
    Reject();
END_IF;
```

## When ignoring is legitimate

- The expression is generated and intentionally constant.
- The operands are complex expressions whose equality requires domain-specific
  semantics; those are not reported by this rule.

## How to fix

Compare the variable with the intended second value, or simplify the control
flow if the constant result is deliberate.
