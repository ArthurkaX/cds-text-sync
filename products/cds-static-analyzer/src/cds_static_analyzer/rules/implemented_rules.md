# Implemented rules

- CTS0001 — Commented-out code
- CTS0002 — Unused input
- CTS0003 — CASE without ELSE
- CTS0004 — Magic numeric literal
- CTS0006 — Array index outside bounds
- CTS0007 — Structural indentation
- CTS0008 — Variable declaration alignment
- CTS0009 — Output not assigned
- CTS0010 — Redundant boolean IF
- CTS0011 — Assigned local not read
- CTS0012 — Overwrite without read
- CTS0013 — Declared symbol not referenced
- CTS0014 — Floating-point equality
- CTS0015 — Duplicate CASE label
- CTS0016 — Unreachable code after control-flow exit
- CTS0017 — Constant control-flow condition
- CTS0018 — Read before assignment
- CTS0019 — Output not assigned on all paths
- CTS0020 — Write to input variable
- CTS0021 — Self-assignment
- CTS0022 — Output read before assignment
- CTS0023 — Empty statement
- CTS0024 — Multiple output writes
- CTS0025 — Concurrent access to shared data, including cross-task write/read races
- CTS0026 — Overlapping AT memory areas
- CTS0027 — Temporary function-block instance
- CTS0028 — Suspicious STRING operation
- CTS0029 — Multiple calls to one function-block instance
- CTS0030 — Modifying a FOR loop control variable inside the loop
- CTS0031 — Conditional function-block call
- CTS0032 — Stateless function block
- CTS0033 — Variable could be declared CONSTANT
- CTS0034 — Ignored function return value
- CTS0035 — Division by literal zero
- CTS0036 — Duplicate IF condition
- CTS0037 — No-op control-flow branch
- CTS0038 — Invalid FOR loop step
- CTS0039 — FOR range exceeds array bounds
- CTS0040 — Shift amount outside operand width
- CTS0041 — Bit index outside type width
- CTS0042 — Zero timer preset time
- CTS0043 — Comparison outside type range
- CTS0044 — Overlapping CASE range
- CTS0045 — Unreachable POU
- CTS0046 — REPEAT condition not changed
- CTS0047 — Self-comparison
- CTS0048 — Constant control-flow expression
- CTS0049 — Constant arithmetic overflow
- CTS0050 — Possible zero divisor
- CTS0051 — Escaping local address
- CTS0052 — FB output before call
- CTS0053 — Unresolved call
- CTS0054 — Implicit narrowing conversion
- CTS0055 — Mixed signed and unsigned comparison
- CTS0057 — Inadequate FOR counter type
- CTS0058 — TIME literal outside range
- CTS0059 — Unsafe enumeration use
- CTS0060 — Unchecked pointer dereference
- CTS0061 — Unchecked reference use
- CTS0062 — Implicit TIME and numeric arithmetic
- CTS0063 — Inconsistent MEMCPY/MemMove size
- CTS0064 — Retained pointer
- CTS0072 — Escaping address of VAR_OUTPUT
- CTS0073 — Missing public POU documentation
- CTS0075 — Function result not assigned on all paths
- CTS0076 — VAR_IN_OUT never written

## Pending — correctness analyzer

### Types and arithmetic

- Integer division assigned to a floating-point result.

### Arrays and memory

- `__NEW`/`__DELETE` in cyclic tasks.

### Strings

- `STRING(n)` assignment that can truncate the destination.
- `CONCAT` chain whose provable length exceeds the destination capacity.
- String literal longer than the declared destination.

### Control flow and logic

- `WHILE` condition variable not changed in the loop body.
- Tautological or contradictory boolean expression (`x AND NOT x`,
  `x OR TRUE`).
- Reliance on short-circuit evaluation for pointer safety.
- `SEL`/`MUX` arguments with side effects.
- Ambiguous `AND`/`OR` precedence without parentheses.
- Identical branch bodies.
- Recursive POU call graph.

### POU and function-block lifecycle

- Function result not assigned on every path.
- Reading timer `.Q` without calling the timer in the current cycle.
- Conditional or non-periodic `R_TRIG`/`F_TRIG` invocation.
- `VAR_IN_OUT` that is never written.
- `FUNCTION` with global side effects.
- Empty or unreachable POU/method/action.
- POU complexity and size metrics.
- Project-wide duplicated code blocks.

### Declarations and project structure

- Local/global or member shadowing.
- Global writes without task ownership.
- Global used by exactly one POU.
- Naming convention violations by type and declaration section.
- Direct `%IX`/`%QX`/`%MW` address in implementation code.
- `AT` on a local POU variable.
- Invalid or incomplete `PERSISTENT` declarations.
- Missing initial values for state enums/structures.
- Non-constant array bounds or arrays above the configured size limit.
- Use of deprecated library functions.

## Pending — separate formatter/linter tool

These checks should support autofix and remain separate from correctness
analysis:

- Mixed tabs and spaces.
- Trailing whitespace.
- Maximum line length.
- Inconsistent keyword casing.
- Multiple statements on one line.
- Configurable naming conventions.
