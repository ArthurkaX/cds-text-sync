# Tests

Two kinds of tests:

- **ST tests in simulation** (`cts test`): tests written in ST, in a test
  application that only ever runs in simulation. For the logic of POUs.
- **JSON test plans** (`cts verify --with-test`): variable writes and reads
  against an application online, on a PLC or in simulation.

When the project already has its test application (`cts test` runs rather
than refuses), a new POU and its test take four steps: write the POU's `.st`
at the top of `project-view/` (shared by every application), add its
`Check`/`CheckReal` calls to `PRG_Tests.st`, `cts import`, `cts test`. The
rest of this guide sets the test application up and explains the plans.

## ST tests in simulation

The POUs in the POUs view are shared by every application of the project. A
second device holds the tests:

```text
PLC_Main                      the device of the real PLC
  Plc Logic/Application       the production application (active)
Test                          a second device, always in simulation
  Plc Logic/TestApp
    Library Manager           with CmpLog (the runtime's log) and Standard
    TestResult                GVL: the counts cts reads
    TestLog                   FUNCTION: writes one CTS| record to the log
    Check, CheckReal          FUNCTION: count and log one check
    PRG_Tests                 PROGRAM: the tests
    Task Configuration/TestTask   calls PRG_Tests
POUs                          the project root, shared: the code under test
  F_Clamp
```

In the sync folder the project root is the top of `project-view/`
(`project-view/F_Clamp.st`); the test application's objects are under
`project-view/Test/Plc Logic/TestApp/`.

`cts test` makes TestApp the active application, downloads it to the
simulation, starts it, waits until `TestResult.Done` is TRUE, reads the
counts, reads the simulation's log from the run's `TEST_START` record on,
logs TestApp out and makes the earlier application active again. A device
that is not in simulation is refused unless `--plc` says the tests may go to
that PLC: then TestApp is downloaded there (the deny list's `download`
applies) and the tests run on the real runtime. `--repeat N` runs them N
times, each run after the first started again by a warm reset when the deny
list allows `reset_plc`, else by another download (`restart=` on the line);
the line counts the failed runs (`failed_runs=`) and names each failing test
with its run, which finds a test that fails now and then. The records reach
the log a moment after `TestResult.Done`: each run waits up to 5 s for its
own `TEST_START` and as many results as the counts; a run whose `TEST_START`
does not come did not run (its counts are an earlier run's) and fails. Exit 0 when every test of every run passed.

Every run leaves its log: the records the tests wrote and whatever the
runtime logged meanwhile (an exception, a watchdog), in the runtime's log
file format. It goes to `--out` (a file, or a folder for
`<application>.log`), else to `<sync folder>/.git/cts/test/<application>.log`;
the line names it as `log=`.

```bash
cts test                        # TestApp
cts test --app UnitTests --wait 60 --out results/
```

```text
ok test passed=3 failed=0 application=TestApp device=Test ms=5210 log=C:\plant\.git\cts\test\TestApp.log
error test passed=2 failed=1 application=TestApp device=Test ms=5180 log=C:\plant\.git\cts\test\TestApp.log
  FAIL F_Clamp cuts to hi got=11.0 want=10.0
```

`--json` lists every test as `tests` (`name`, `status` PASS/FAIL, `fields`)
and the run's log entries as `log`.

Set it up once in CODESYS: add a device (the same type as the PLC's is
fine), switch it to simulation (Online -> Simulation while its application is
active), name its application TestApp, add the libraries CmpLog and Standard
(CONCAT) to its Library Manager, and add the GVL, the functions and the
program below with a task that calls `PRG_Tests`. Only the code a task calls is downloaded, so the
tests reach the shared POUs through `PRG_Tests`.

The result GVL, its names fixed:

```iecst
{attribute 'qualified_only'}
VAR_GLOBAL
    Done : BOOL;        // TRUE once every test has run
    Passed : UDINT;
    Failed : UDINT;
END_VAR
```

The log records, one per runtime log entry (`cts plc-log --cts` reads the
same format; an empty result with no malformed records points to the raw log tail):

```text
CTS|M|TEST_START|<application>|      before the first test: the run's log starts here
CTS|M|TEST_PASS|<test>|
CTS|M|TEST_FAIL|<test>|k=v;k=v       what the test saw, e.g. got=11.0;want=10.0
```

A record is cut at 127 characters, so keep test names short, and a value
holds neither `|` nor `;`.

```iecst
FUNCTION TestLog : BOOL
VAR_INPUT
    code : STRING(20);
    tag : STRING(100);
    fields : STRING(100);
END_VAR

CmpLog.LogAdd2(CmpLog.LogConstants.STD_LOGGER, 0, CmpLog.LogClass.LOG_INFO, 0, 0,
    CONCAT(CONCAT(CONCAT('CTS|M|', code), '|'), CONCAT(CONCAT(tag, '|'), fields)));
TestLog := TRUE;
```

One check, and one for numbers that logs what it got. It compares within a
millionth (of the value, or absolute below 1): a computed LREAL rarely
equals its decimal literal bit for bit.

```iecst
FUNCTION Check : BOOL
VAR_INPUT
    ok : BOOL;
    name : STRING(100);
    detail : STRING(100);
END_VAR

IF ok THEN
    TestResult.Passed := TestResult.Passed + 1;
    TestLog('TEST_PASS', name, '');
ELSE
    TestResult.Failed := TestResult.Failed + 1;
    TestLog('TEST_FAIL', name, detail);
END_IF
Check := ok;
```

```iecst
FUNCTION CheckReal : BOOL
VAR_INPUT
    got : LREAL;
    want : LREAL;
    name : STRING(100);
END_VAR

CheckReal := Check(ABS(got - want) <= 1.0E-6 * MAX(1.0, ABS(want)), name,
    CONCAT(CONCAT('got=', LREAL_TO_STRING(got)), CONCAT(';want=', LREAL_TO_STRING(want))));
```

The tests, run once:

```iecst
PROGRAM PRG_Tests

IF NOT TestResult.Done THEN
    TestLog('TEST_START', 'TestApp', '');
    CheckReal(F_Clamp(5, 0, 10), 5, 'F_Clamp keeps a value inside');
    CheckReal(F_Clamp(-1, 0, 10), 0, 'F_Clamp lifts to lo');
    CheckReal(F_Clamp(11, 0, 10), 10, 'F_Clamp cuts to hi');
    TestResult.Done := TRUE;
END_IF
```

A new shared POU and its tests: create it at the project root, add its checks
to `PRG_Tests`, carry both into the IDE and run the tests.

```bash
# pou: the object kind; --kind: which POU
cts new pou F_Lerp --kind function --return-type REAL --parent . \
  --text "VAR_INPUT a, b, t : REAL; END_VAR F_Lerp := a + (b - a) * t;"
# PRG_Tests.st: CheckReal(F_Lerp(0, 10, 0.5), 5, 'F_Lerp halfway');
cts import
cts test
```

`cts test` runs what the IDE holds, saved or not: no `cts save` is needed
between the import and the test, and the test saves nothing.

A test that needs several cycles (a timer, a state machine) keeps its own
step counter in `PRG_Tests` and sets `Done` when the last step has checked;
`--wait` (seconds, default 30) is how long cts waits for it.

## JSON test plans

`cts verify --with-test` runs JSON test plans against a CODESYS online
application. The in-IDE agent runs them (`test.run`), one agent call per step:
login, start, variable writes and reads. A `wait` step does not hold the IDE,
which stays usable while a plan runs.

### Location

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
cts verify --with-test --test-file arithmetic.json
```

Run all plans from `.test/` in sorted order:

```bash
cts verify --with-test
```

The agent method directly:

```bash
cts raw run_tests --folder <sync-folder> --file arithmetic.json --timeout 120
```

### Plan Object

Every plan names the CODESYS application under test, and that application
must be the active one in the IDE: a plan for another application is refused,
not switched to.

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
| `ip` | string | no | PLC IP. If omitted, the project online configuration is used. |
| `gateway` | string | no | Gateway name, with `ip`. Default: `Gateway-1`. |
| `start` | bool | no | Start application before steps. Default: `true`. |
| `timeout` | number | no | Plan timeout in milliseconds. Default: 60000. |
| `continue_on_fail` | bool | no | Continue after failed tests. Default: `false`. |
| `reset` | string | no | `"cold"` performs one cold reset before the first plan that asks for it. |
| `tests` | array | yes | Test cases to execute. |

Before each plan, the agent logs in to the active application (`cts connect`:
no online change, no download), checks it is the plan's application, resets
and starts it as the plan says, then executes the tests in order.

### Test Object

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
| `timeout` | number | no | Test timeout in milliseconds, within the plan's. |
| `continue_on_fail` | bool | no | Continue steps after a failed step. |
| `steps` | array | yes | Steps to execute in order. |

### Steps

#### write

```json
{ "action": "write", "variable": "MAIN.fbArith.rA", "value": 10.0 }
```

Writes one online variable. A JSON bool goes as `TRUE`/`FALSE`, a number as
its text; a string is the IEC literal as written (`WORD#5`, `E_Mode.Run`).

#### wait

```json
{ "action": "wait", "ms": 200 }
```

Waits for the requested number of milliseconds (default 100), cut short at
the timeout.

#### read

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

#### assert

```json
{ "action": "assert", "variable": "MAIN.fbArith.xDone", "expected": true }
```

The same as `read`.

### Values

A read gives the value as the IDE holds it: a BOOL as `true`/`false`, a number
as a number, anything else as the IDE's text. `expected` compares a bool with
a bool, a number within `tolerance`, and text ignoring case against the value
or the IDE's spelling of it (`E_Mode.Run`).

### FB Testability Rule

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

### Edge Triggers

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

### Result

The CLI returns structured JSON.

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

`results` holds one report per plan: the tests, and per test its steps with
`status`, the value read and the `error` of a failed step.

### Common Failures

| Error | Meaning | Fix |
| --- | --- | --- |
| `Test plan must name its application` | Missing `application`. | Add the exact CODESYS application name. |
| `... but the active application is '...'` | The plan's application is not the active one. | Make it the active application in the IDE. |
| `Not connected` | No PLC session. | Check the PLC address, then `cts connect`. |
| `read X: ...` | The variable is not in the online application. | Check the variable path; an unreferenced variable is not downloaded. |
| Assertion mismatch | PLC logic ran but value did not match. | Inspect the failing step in `results`. |
