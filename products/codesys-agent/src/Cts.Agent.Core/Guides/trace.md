# PLC trace: record a moment, then read it

Use this to catch what happens right now: a pump that trips, a step that hangs, a value that jumps. The PLC records the variables in a task's cycle into a ring buffer, keeping the last samples, until you stop it or until a trigger and the samples after it. Then `cts trace pull` reads the buffer into a CSV and a summary. It is CODESYS' own Trace, the object `CtsTrace` of the active application, so the engineer sees the same trace in the IDE's Trace editor.

Trace or trend:

- `cts trace` is for now: seconds to minutes, every cycle, a trigger, no download of the application.
- `cts trend` is for overnight: hours to days into a file on the PLC, asked later with SQL (`cts guide trend`).

## Set it up and start it

```
cts connect                                      (the IDE logged in; the application keeps running)
cts trace set GVL_IO.rLevel PLC_PRG.fbPump.xRun  (makes CtsTrace, or changes it)
cts trace start                                  (downloads the trace only, and starts it)
```

- `cts trace set VAR ...` replaces the list of variables. Without VAR the list stays and only the options change. Name each variable as the IEC code names it: `GVL_IO.rLevel`, `PLC_PRG.fbPump.xRun`.
- `--task NAME` sets the task whose cycle is recorded. A new trace takes the fastest cyclic task that runs the program. `--every N` records every Nth cycle.
- `--samples N` sets how many samples per variable the PLC keeps: the last N. A new trace keeps 1000.
- A trace is not code. `cts trace set` works while the IDE is online, and `cts trace start` downloads only the trace: the application keeps running unchanged.
- `cts trace start` replaces the trace the PLC had, and its samples. It needs the IDE logged in to an application that runs the code the IDE has; after an edit, download first (`cts guide deploy`).
- `cts trace` shows the setup and, when the PLC holds the trace, its `state`, `trigger_state` and `count` of samples.

## Without a trigger

The trace records until `cts trace stop` and keeps the last `--samples`. `cts trace pull` reads them while it records or after it stopped. A later `cts trace start` starts over with an empty buffer.

## With a trigger

```
cts trace set --trigger PLC_PRG.fbPump.xFault              (rising edge; half the buffer after it)
cts trace set --trigger GVL_IO.rLevel --level 90 --post 100
cts trace start
cts trace pull --wait 600
```

- `--trigger VAR` makes the trace wait for VAR to change. It records all the time, keeps the last samples, and stops `--post` samples after the trigger: the moments before and after it.
- `--edge rising|falling|both`: the change that counts. A first trigger takes `rising`. For a number, `--level VALUE` makes the crossing of VALUE the change.
- `--post N` sets how many samples follow the trigger. A first trigger takes half the buffer.
- `cts trace pull --wait N` waits up to N seconds for the trace to stop, then reads it. `trigger_ms` is the trigger's moment on the samples' clock. When the trace still records after N seconds, the pull reads the samples so far.
- `--no-trigger` removes the trigger.

## Only some cycles

`--condition VAR` records only the cycles where the BOOL VAR is TRUE, for example while a step is active. `--no-condition` records every cycle again.

## Read it

- `cts trace pull` reads the buffer without changing it, and needs no login. It writes a CSV with one row per sample: the time in ms from the trace's start (`t_ms`), then one column per variable. A BOOL is 0 or 1. `--csv FILE` names the file; by default it is the same file on this PC for each pull.
- For each variable, the summary gives its type, first and last value, minimum and maximum, and the number of changes. For a variable that changed at most 10 times it also lists when each change happened.
- The summary often answers the question by itself: when xFault went 0->1, what rLevel was at that moment. For more, read the CSV.
