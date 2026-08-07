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
- CTS0065 — Partial array coverage
- CTS0067 — Non-strict enumeration
- CTS0068 — Direct hardware address in executable logic
- CTS0069 — Single-element array
- CTS0070 — Shadowed symbol
- CTS0071 — Large variable
- CTS0072 — Escaping address of VAR_OUTPUT
- CTS0073 — Missing public POU documentation
- CTS0075 — Function result not assigned on all paths
- CTS0076 — VAR_IN_OUT never written
- CTS0077 — Integer division assigned to floating point
- CTS0078 — String literal exceeds declared capacity
- CTS0079 — String assignment may truncate the destination
- CTS0080 — CONCAT result exceeds string capacity
- CTS0081 — Tautological or contradictory boolean expression
- CTS0082 — Pointer guard relies on short-circuit evaluation
- CTS0083 — SEL/MUX argument may have side effects
- CTS0084 — Identical control-flow branch bodies
- CTS0085 — Recursive POU call cycle
- CTS0086 — Uninitialized interface use
- CTS0087 — Conditional edge-trigger call
- CTS0088 — Stateful function-block assignment
- CTS0089 — Global state access during FB_Init
- CTS0090 — Overridable method called from FB_Init
- CTS0091 — Implicit pointer conversion
- CTS0092 — Pointer dereference in declaration initializer
- CTS0093 — Reference use in declaration initializer
- CTS0094 — Unused function-block output
- CTS0095 — Local variable uses AT hardware mapping
- CTS0096 — Function writes global state
- CTS0097 — Empty callable implementation
- CTS0098 — Mixed AND and OR without parentheses
- CTS0099 — Dynamic memory operation

## Pending — correctness analyzer

### Types and arithmetic


### Arrays and memory


### Strings

### Control flow and logic

- `WHILE` condition variable not changed in the loop body.

### POU and function-block lifecycle

- Unreachable POU/method/action is covered by CTS0045.
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
