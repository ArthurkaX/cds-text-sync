# PLC trend: record variables, then analyse them

Use this for commissioning: pick variables, have the PLC record them in a task's cycle to an SQLite file on the PLC, copy that file to this PC, then analyse it with SQL. The PLC does the recording, so it keeps going without the IDE or the network, at the task's rate. It is CODESYS' own Trend Recording, made from files; no IDE click needed.

## Set it up

```
cts trend set GVL_IO.rLevel GVL_IO.rFlow PLC_PRG.fbPump.xRun     (offline: writes the files)
cts import
cts build
cts download                     (the first time: a full download)
cts trend on                     (the recording is off after every download and restart)
```

- `cts trend set VAR ...` writes the Trend Recording `CtsTrend` into the sync folder. The first time it also writes the Trend Recording Manager and its task, `GVL_CtsTrend` and the `VisuTrendStorageAccess` library reference. The list replaces the previous list. Without VAR the list stays and only the options change.
- Name each variable as the IEC code names it: `GVL_IO.rLevel`, `PLC_PRG.fbPump.xRun`, `GVL_IO.arTemp[3]`. A STRING is not recorded.
- `--task NAME` sets the task whose cycle is recorded. The default is the fastest cyclic task that runs the program. `--every N` records every Nth cycle. `cts trend` shows the setup and `interval_ms`, the time between two samples.
- The recording has a fixed number of slots: `--slots`, default 10. A free slot records `GVL_CtsTrend.xRecord`.
  - New variables in the same number of slots go to the PLC as an online change (`cts download --online-change`).
  - A new slot count, the first trend, or a variable from a GVL the PLC does not have yet needs a full download.
- `--limit-mb` sets how big the PLC's file may grow; the default is 16 MB. At the limit the PLC drops its oldest rows. Pull before that happens: the database on this PC keeps everything earlier pulls brought.
- The PLC can lose samples when it cannot store them fast enough: many variables at a 1 ms task. `cts trend pull` reports this as gaps. Use fewer variables or `--every`.

## Record

`cts trend on` and `cts trend off` write `GVL_CtsTrend.xRecord`. An engineer can do the same in the IDE: write TRUE or FALSE to it with Ctrl+F7. The recording is off after a download or a restart. An online change keeps it as it was.

## Pull and analyse

```
cts trend pull
cts trend query "SELECT name, count(*), min(value), max(value), avg(value) FROM samples GROUP BY name"
cts trend query "SELECT at, value FROM samples_at WHERE name = 'GVL_IO.rLevel' ORDER BY ts DESC LIMIT 20"
```

- `cts trend pull` needs the IDE logged in (`cts connect`).
  - While the recording is on, it pauses the recording for the copy, so the copy is consistent. The pause lasts a few seconds (`paused_s`) and then the recording goes on.
  - The PLC holds back about the last second before the pause; the next pull brings it.
  - It reports `rows`, `gaps`, `added` (samples new to this PC) and the time span.
- The database lives on this PC, one per project and application; the pull prints its path. Its tables:
  - `samples(ts, name, value)`: one row per variable and cycle. `ts` is µs since 1970 in UTC, as the PLC's clock has it.
  - `samples_at(at, name, value, ts)`: the same rows with `at` as readable text.
  - `variables(name, type)`.
  - `gaps(ts)`: cycles with no values, either while the recording was off (including a pull's pause) or cycles the PLC could not store.
- `value` is what the variable's type reads: a REAL is a number, a BOOL is 0 or 1, INT and DINT are signed, and TIME is in ms.
- `cts trend query` runs one statement, read-only, and shows at most `--limit` rows (default 200; `more=true` says there were more). Its words may be given unquoted: they are joined.

## Questions an analysis asks

- Did a value leave its range? `SELECT at, value FROM samples_at WHERE name = 'GVL_IO.rLevel' AND value > 90`
- When did a BOOL switch? Compare each row with the one before: `SELECT at, value FROM (SELECT at, value, lag(value) OVER (ORDER BY ts) AS before FROM samples_at WHERE name = 'PLC_PRG.fbPump.xRun') WHERE value <> before`
- What did one variable do while another was set? Join `samples` with itself on `ts`: the variables of one cycle share it.
- Did the recording keep up? `SELECT count(*) FROM gaps`, compared with the rows in the same span.
