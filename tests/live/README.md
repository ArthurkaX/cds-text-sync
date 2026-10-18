# Live scenarios

`run.py` drives the real `cts` against a small CODESYS project open in the IDE
and prints one table. It is for the checks that need the IDE and
the in-IDE agent together -- the ones a unit test cannot reach.

## What it needs

* A project root in `CTS_LIVE_PROJECT` (a git working tree with `project-view/`
  and a sync base, `refs/cts/base`); its project must be open in CODESYS with the
  agent running, and the IDE must be offline.
* A clean git tree there: every scenario restores the disk with git, so
  uncommitted work would be lost.

## Running

    set CTS_LIVE_PROJECT=<project root>
    python tests/live/run.py            # every scenario
    python tests/live/run.py <name> …   # a subset

Exit code is 1 if any scenario failed. It runs the checkout's own cts.exe
(`products/codesys-agent/src/Cts.Cli/bin/Release/net48`): build it first.

## Adding a scenario

Add a function `def scenario_<name>(ctx)` that sets something up, runs `cts`
through `ctx.cts(...)`, asserts on the exit code and the verdict line (the
first stdout line, `ok <command> key=value …`), and returns a short detail
string for the table. Do not restore inside it: the runner calls `ctx.restore()`
in a `finally`, which puts the disk back and ends with `cts compare`
reporting no difference. Name an object the fixture must have via
`ctx.st_path(...)`, so a missing one is a clear message, not a traceback.
