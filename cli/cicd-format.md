# CI/CD Test Plan Format

`rp cicd` runs JSON test plans against a CODESYS online application.

## Location

Test plans live in the project sync folder:

```text
<sync-folder>/
├── .test/
│   ├── arithmetic.json
│   ├── counter.json
│   └── traffic-light.json
├── project-view/
└── .dump/
```

If `--file` is omitted, the daemon runs every `*.json` file in `.test/` in sorted order.

```bash
cds-text-sync rp cicd --file arithmetic.json --timeout 60
cds-text-sync rp cicd --file .test/arithmetic.json --timeout 60
cds-text-sync rp cicd --timeout 120
```

## Plan

Every plan must explicitly name the application under test.

```json
{
  "name": "CI/CD Verification Suite",
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

| Field | Type | Description |
| --- | --- | --- |
| `application` | string | Required CODESYS application name to test. The daemon selects it before connecting. |
| `ip` / `device_ip` | string | Optional PLC IP. If omitted, the project online configuration is used. |
| `gateway` / `gateway_name` | string | Optional gateway name, default `Gateway-1`. |
| `start` | bool | Start the application before steps, default `true`. Use `false` when the application is already running. |
| `timeout` | number | Total plan timeout in ms. |
| `continue_on_fail` | bool | Continue after failed tests, default `false`. |
| `reset` | string | Optional: `"cold"` performs a cold reset before running tests — stops PLC, resets cold, reconnects, builds (online change), and starts PLC. Clears all FB memory for a clean slate. Default: no reset. |
| `tests` | array | Test cases to execute. |

Before each plan, the daemon selects the requested application, then connects/logs in. Login performs the normal CODESYS online-change/download flow when CODESYS requires it. If `start` is omitted, the daemon starts the application by default; an already-running application is treated as OK by the updated daemon.

## Test

```json
{
  "name": "FB_Arithmetic add",
  "timeout": 5000,
  "continue_on_fail": false,
  "steps": [
    { "action": "write", "variable": "MAIN.fbArith.rA", "value": 10.0 },
    { "action": "wait", "ms": 200 },
    { "action": "read", "variable": "MAIN.fbArith.rResult", "expected": 13.0, "tolerance": 0.001 }
  ]
}
```

| Field | Type | Description |
| --- | --- | --- |
| `name` | string | Test name. |
| `timeout` | number | Test timeout in ms, inherited from plan if omitted. |
| `continue_on_fail` | bool | Continue steps after a failure. |
| `steps` | array | Sequential steps. |

## Steps

### write

```json
{ "action": "write", "variable": "MAIN.fbArith.rA", "value": 10.0 }
```

Writes a PLC variable through the online API.

### wait

```json
{ "action": "wait", "ms": 200 }
```

Waits for the requested number of milliseconds.

### read

```json
{ "action": "read", "variable": "MAIN.fbArith.rResult", "expected": 13.0, "tolerance": 0.001 }
```

Reads a PLC variable and optionally validates `expected`, `expected_min`, `expected_max`, and `tolerance`.

### assert

```json
{ "action": "assert", "variable": "MAIN.fbArith.xDone", "expected": true }
```

Reads a PLC variable and checks exact equality.

## Validation Rules

1. `expected`: numeric values use `abs(actual - expected) <= tolerance`.
2. `expected_min` / `expected_max`: actual value must stay within the range.
3. `BOOL#TRUE` and `BOOL#FALSE` are parsed as booleans.
4. Typed CODESYS values such as `REAL#13.0` and `INT#5` are parsed before comparison.

## MAIN Requirement

`MAIN` must call FBs in pass-through style, otherwise online writes are overwritten on the next PLC cycle.

```iecst
// Wrong
fbArith(rA := 0.0, rB := 0.0, eOp := 0, xExecute := FALSE);

// Correct
fbArith(rA := fbArith.rA, rB := fbArith.rB,
        eOp := fbArith.eOp, xExecute := fbArith.xExecute);
```

## Result

The CLI returns detailed JSON. The dashboard shows concise file-level status lines such as `PASS arithmetic.json (1/1)` plus a suite summary.

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
      "plan": "CI/CD Verification Suite",
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

`results` contains the detailed per-step report for agents and CI logs.

## Diagnostics

Use the CLI for details when the dashboard shows `FAIL`:

```bash
cds-text-sync rp cicd --file arithmetic.json --timeout 120
```

Common failures:

| Error | Meaning | Fix |
| --- | --- | --- |
| `Test plan must specify the target application` | The JSON file has no `application` field. | Add the exact CODESYS application name, for example `CI_CD_Application`. |
| `Application '...' not found` | The plan names an application that is not in the active project. | Check `cds-text-sync rp project_tree --depth 4 --timeout 30`. |
| `Invalid expression` | A variable path is not exported to the online application. | Check the variable path and symbol/export settings. |
| Assertion/read mismatch | PLC logic ran, but expected value did not match. | Inspect the failing step in `results[].tests[].steps[]`. |
