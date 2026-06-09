# Test Plan Format

`cts test` runs JSON test plans against a CODESYS online
application. The command is a user-facing wrapper around the daemon's `cicd`
method.

## Location

Test plans live in the project sync folder:

```text
<sync-folder>/
  .test/
    arithmetic.json
    counter.json
  project-view/
  .dump/
```

Run one file:

```bash
cts test --file arithmetic.json --timeout 120
```

Run all plans from `.test/` in sorted order:

```bash
cts test --timeout 120
```

Compatibility form:

```bash
cts raw cicd --file arithmetic.json --timeout 120
```

## Plan Object

Every plan must name the CODESYS application under test.

```json
{
  "name": "Arithmetic smoke test",
  "application": "CI_CD_Application",
  "ip": "192.0.2.10",
  "gateway": "Gateway-1",
  "start": false,
  "timeout": 30000,
  "continue_on_fail": false,
  "tests": [
    {
      "name": "add",
      "steps": [
        { "action": "wait", "ms": 100 }
      ]
    }
  ]
}
```

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `name` | string | no | Human-readable plan name. |
| `application` | string | yes | CODESYS application name. |
| `ip` / `device_ip` | string | no | PLC IP. If omitted, the project online configuration is used. |
| `gateway` / `gateway_name` | string | no | Gateway name. Default: `Gateway-1`. |
| `start` | bool | no | Start application before steps. Default: `true`. |
| `timeout` | number | no | Plan timeout in milliseconds. |
| `continue_on_fail` | bool | no | Continue after failed tests. Default: `false`. |
| `reset` | string | no | `"cold"` performs one cold reset before the suite. |
| `tests` | array | yes | Test cases to execute. |

Before each plan, the daemon selects the requested application, connects/logs
in, optionally starts the application, then executes tests sequentially.

## Test Object

```json
{
  "name": "FB_Arithmetic add",
  "timeout": 5000,
  "continue_on_fail": false,
  "steps": [
    { "action": "write", "variable": "MAIN.fbArith.rA", "value": 10.0 },
    { "action": "write", "variable": "MAIN.fbArith.rB", "value": 3.0 },
    { "action": "wait", "ms": 200 },
    { "action": "read", "variable": "MAIN.fbArith.rResult", "expected": 13.0, "tolerance": 0.001 }
  ]
}
```

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `name` | string | no | Human-readable test name. |
| `timeout` | number | no | Test timeout in milliseconds. |
| `continue_on_fail` | bool | no | Continue steps after a failed step. |
| `steps` | array | yes | Steps to execute in order. |

## Steps

### write

```json
{ "action": "write", "variable": "MAIN.fbArith.rA", "value": 10.0 }
```

Writes one online variable.

### wait

```json
{ "action": "wait", "ms": 200 }
```

Waits for the requested number of milliseconds.

### read

```json
{
  "action": "read",
  "variable": "MAIN.fbArith.rResult",
  "expected": 13.0,
  "tolerance": 0.001
}
```

Reads one online variable. If expectation fields are present, the step also
asserts the value.

Supported expectation fields:

| Field | Meaning |
| --- | --- |
| `expected` | Exact expected value. Numeric values use `tolerance`. |
| `expected_min` | Minimum accepted numeric value. |
| `expected_max` | Maximum accepted numeric value. |
| `tolerance` | Allowed absolute numeric delta. |

### assert

```json
{ "action": "assert", "variable": "MAIN.fbArith.xDone", "expected": true }
```

Reads one online variable and checks the expected value.

## Value Parsing

The runner parses common CODESYS typed values before comparison:

| Raw value | Parsed value |
| --- | --- |
| `BOOL#TRUE` | `true` |
| `BOOL#FALSE` | `false` |
| `REAL#13.0` | `13.0` |
| `INT#5` | `5` |

## FB Testability Rule

For online tests, `MAIN` must pass FB instance fields through to the FB call.
Otherwise the PLC program overwrites values written by the CLI before the FB
can use them.

Wrong:

```iecst
fbArith(rA := 0.0, rB := 0.0, eOp := 0, xExecute := FALSE);
```

Correct:

```iecst
fbArith(rA := fbArith.rA, rB := fbArith.rB,
        eOp := fbArith.eOp, xExecute := fbArith.xExecute);
```

## Edge Triggers

Online writes are committed individually. The PLC may execute a cycle between
two writes. If an FB uses a rising-edge trigger, a fast `false -> true`
transition can be missed.

For FBs that are tested through the online API, prefer continuous execution:

```iecst
IF xExecute THEN
    rResult := rA + rB;
    xDone := TRUE;
ELSE
    xDone := FALSE;
END_IF
```

If rising-edge logic is required, add an explicit wait between reset and
trigger writes:

```json
{ "action": "write", "variable": "MAIN.fbArith.xExecute", "value": false },
{ "action": "wait", "ms": 100 },
{ "action": "write", "variable": "MAIN.fbArith.xExecute", "value": true }
```

## Result

The CLI returns structured JSON. The daemon dashboard intentionally shows only
short status lines such as `PASS arithmetic.json (1/1)`.

Typical result shape:

```json
{
  "status": "SUCCESS",
  "ok": true,
  "summary": {
    "ok": 3,
    "not_ok": 0,
    "total": 3,
    "files": 2
  },
  "files": [
    {
      "file": "arithmetic.json",
      "plan": "Arithmetic smoke test",
      "status": "SUCCESS",
      "ok": true,
      "tests_ok": 2,
      "tests_failed": 0,
      "total_ms": 512
    }
  ],
  "results": []
}
```

`results` contains detailed per-step reports for CI logs and agents.

## Common Failures

| Error | Meaning | Fix |
| --- | --- | --- |
| `Test plan must specify the target application` | Missing `application`. | Add the exact CODESYS application name. |
| `Application '...' not found` | Wrong application name. | Run `cts project-tree --depth 4`. |
| `Invalid expression` | Variable is not exported to the online application. | Check variable path and symbol export. |
| Assertion mismatch | PLC logic ran but value did not match. | Inspect the failing step in `results`. |
