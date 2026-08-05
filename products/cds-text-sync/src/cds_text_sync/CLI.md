# cds-text-sync CLI

This document is the command contract for the simplified `cds-text-sync` CLI.
The CLI has one normal transport: it talks to `Project_daemon.py` running inside
CODESYS. The old `rp` spelling is only a compatibility alias for raw daemon
commands.

## Startup

A human starts the bridge once per CODESYS session:

1. Open the project in CODESYS.
2. Run `Project_daemon.py` from Tools -> Scripting -> Execute Script.
3. Keep the daemon dashboard open while using the CLI.

Install the console command with:

```bash
python -m pip install -e .
```

Both console names are installed:

```text
cts
cds-text-sync
```

The short `cts` spelling is used in examples.

Then check the daemon:

```bash
cts ping --timeout 10
cts status --timeout 10
```

`stdout` is JSON by default. Human diagnostics go to `stderr`.

Use text output when reading results manually:

```bash
cts --output text status
```

## Main Sync Commands

These are the primary commands for editing CODESYS projects as text.

| Command | Direction | Meaning | Timeout |
| --- | --- | --- | --- |
| `status` | daemon -> CLI | Show daemon, project, and sync-folder state. | 10s |
| `export` | IDE -> disk | Export the open IDE project and overwrite `project-view/`. | 60s |
| `compare` | IDE vs disk | Compare the open IDE project against `project-view/`. | 60s |
| `import` | disk -> IDE | Build `IMPORT.xml` from `project-view/` and apply it to the IDE project. | 120s |

Normal edit cycle:

```bash
cts export --timeout 60
# edit files in project-view/
cts compare --timeout 60
cts import --timeout 120
cts build --timeout 120
```

`import` options:

| Flag | Meaning |
| --- | --- |
| `--dry-run` | Show what would change without applying (runs compare). |
| `--force-online` | Skip the offline preflight check; use only when you are sure the IDE is offline. |

Rules:

- `export` is destructive for local text files: it refreshes `project-view/`
  from the IDE state.
- `import` treats disk as the source of truth.
- Adding new objects requires the IDE project to be offline. Run
  `disconnect` before `import` when new GVL, DUT, POU, or folder objects were
  added on disk. If `disconnect` does not clear the online state, use
  `cts import --force-online` or `cts raw sync_import_text force_online=true`.
- `build` compiles in the IDE only. It does not guarantee that the PLC is
  running the new code.

## Build And PLC Commands

| Command | Meaning | Requires | Timeout |
| --- | --- | --- | --- |
| `build` | Compile the active application in the IDE. | daemon | 120s |
| `connect [--ip IP]` | Login/connect to the configured PLC or explicit IP. | daemon + device | 60s |
| `disconnect` | Logout from the PLC. | daemon | 15s |
| `download [--start 0|1]` | Force a full download to PLC. Use after adding new objects. | online/device | 120s |
| `start` | Start PLC application. | online | 25s |
| `stop` | Stop PLC application. | online | 25s |
| `app-state` | Show application run/stop/login state. | daemon | 10s |
| `plc-crc` | Compare PLC `Application.crc` with the local IDE build output. | online | 30s |

Deploy existing online-changeable edits:

```bash
cts import --timeout 120
cts build --timeout 120
cts connect --timeout 60
cts plc-crc --timeout 30
```

Deploy newly added objects:

```bash
cts disconnect --timeout 15
cts import --timeout 120
cts build --timeout 120
cts download --timeout 120
cts plc-crc --timeout 30
```

`plc-crc --build` will build the project first, then compare CRCs.

```bash
cts plc-crc --build --timeout 120
```

`connect` uses the normal CODESYS login flow. If the change cannot be handled
as an online change, use `download`.

## Variables

| Command | Meaning | Requires |
| --- | --- | --- |
| `read NAME` | Read one online variable/expression. | online |
| `write NAME VALUE` | Write one online variable/expression and read it back. | online + permission |
| `read-vars EXPR... [--file FILE]` | Batch-read expressions. | online |
| `variable-map` | Build an offline CSV map from `project-view/`. | exported project-view |
| `variable-snapshot` | Read live values for mapped scalar leaves to CSV. | online |
| `variable-restore --input FILE [--apply]` | Restore values from a snapshot CSV. Dry-run by default. | online + permission |

Examples:

```bash
cts read MAIN.fbArith.rResult --timeout 25
cts write GVL_HMI.HMI_start TRUE --timeout 25
cts read-vars MAIN.a MAIN.b --timeout 30
cts variable-map --path GVL_HMI
cts variable-snapshot --path GVL_HMI --out snap.csv --timeout 120
cts variable-restore --input snap.csv --apply --timeout 120
```

## Tests

`test` runs JSON test plans against the online PLC application.

```bash
cts test --file arithmetic.json --timeout 120
cts test --timeout 120
```

Plans live in `<sync-folder>/.test/`. If `--file` is omitted, all `*.json`
plans are executed in sorted order. See [TEST_FORMAT.md](TEST_FORMAT.md) for the
JSON schema and examples.

## Static Analysis (`cts analyze`)

`cts analyze` runs offline static analysis over the exported `project-view/`
tree. It never talks to the daemon and never reads `.dump/`, so it works with no
CODESYS running.

| Subcommand | Meaning |
| --- | --- |
| `analyze [options]` (or `analyze run`) | Run the analysis. |
| `analyze rules` | List the registered rules and their severities. |
| `analyze explain CTS0001` | Show one rule's documentation. |
| `analyze selftest` | Run every rule against its own documentation examples. |
| `analyze baseline create\|update\|check` | Manage the finding baseline. |
| `analyze triage --apply decisions.json` | Apply pre-approved suppress / fix-later decisions. |

Key flags:

| Flag | Meaning |
| --- | --- |
| `--workspace DIR` | Sync folder containing `project-view/` (default: nearest ancestor with `cts-analyze.toml` + `project-view`). |
| `--project-view DIR` | Explicit project-view directory. Mutually exclusive with `--workspace`. |
| `--rule CTS0001` | Restrict the run to one rule id (repeatable). |
| `--fail-on danger\|suspicious\|style` | Exit 1 when findings at/above this severity exist (default: `suspicious`). |
| `--incomplete warn\|error\|ignore` | Policy for incomplete analysis (default: `warn`; `error` exits 3). |
| `--format json\|text\|sarif\|md` | Output format (default: `json`). |
| `--pretty`, `-p` | Shortcut for `--format text`. |

Severities are `danger`, `suspicious`, and `style`. A run distinguishes
*findings* (a rule fired — a problem in the project) from *diagnostics* (the
analysis itself could not provide a declared capability, for example a file it
could not read); a run that is only partially complete is never silently
"clean".

One diagnostic is worth calling out: `project-stale`. The analyzer compares the
XML recorded in `.dump/manifest.json` against the `project-view/` projections
and reports it when the XML is newer — that is, the project moved forward and
nobody re-exported, so the analysis would otherwise describe code that no longer
exists. Run `cts export` and analyse again. The reverse (a locally edited `.st`
newer than its XML) is the normal text-first workflow and is never reported. The
check is best-effort and stays silent when there is no sync state; if a
`git checkout` shuffles timestamps into a false alarm, `--incomplete ignore`
keeps it out of the exit code.

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Quality policy passed. |
| `1` | Unsuppressed findings at or above `--fail-on`. |
| `2` | Configuration error or analysis cannot start. |
| `3` | Incomplete analysis with `--incomplete=error`. |

The workspace is resolved in this order: an explicit `--workspace`; the nearest
ancestor directory that contains both a `cts-analyze.toml` and a
`project-view/`; or an explicit `--project-view`. There is no daemon lookup, and
passing both `--workspace` and `--project-view` is an error.

The static analyzer's user-facing input and findings are Structured Text
(`.st`) only. Visualization XML is intentionally outside this contract and
is handled by the separate machine-oriented `cts visu-lint` command below.

### `cts-analyze.toml`

Configuration lives in a `cts-analyze.toml` next to `project-view/`. It sets
the quality policy, overrides per-rule severity and enabled state, tunes
per-rule options, and scopes rules to path globs:

```toml
[analyze]
fail_on = "suspicious"
incomplete = "warn"

[rules.CTS0006]        # rule-level override
enabled = true
severity = "danger"

[rules.CTS0004]
enabled = true
options.min_occurrences = 2

[[rule_scope]]
path = "POUs/**"
enabled = true
exclude = ["CTS0004", "CTS0007"]
```

Some rules are opt-in and disabled by default: they run only when selected
explicitly with `--rule CTSxxxx` or enabled in the config with
`[rules.CTSxxxx] enabled = true`.

### State and directives

The analyzer keeps its state in `<sync-folder>/.cts-analyze/`, never inside
`project-view/` (that tree is owned by the sync engine):

- `baseline.json` — machine-written lock file, one entry per finding.
- `suppressions.toml` — human + triage written; every entry carries a mandatory
  `reason`.
- `session.json` — resumable triage session.

Individual source files can disable rules with an inline directive. The text
before `--` is the rule list, the remainder is a mandatory human-readable
reason:

```st
// cts:ignore-file CTS0001 -- legacy pattern kept for cross-revision compat
```

`cts ui` opens the same offline analysis in a local desktop interface. It
requires the optional UI dependency (`pip install 'cds-text-sync[ui]'`).

## Project And Object Tools

These commands are useful for diagnostics and targeted maintenance, but they
are not part of the normal edit cycle.

| Command | Meaning |
| --- | --- |
| `project-info` | Show open project metadata, Summary fields, and all Project Information properties. |
| `project-tree [--depth N]` | Show the CODESYS project object tree. |
| `read-object [--path PATH] [--name NAME] [--guid GUID]` | Read one project object. `--name` is the most reliable selector. `--path` uses forward slashes, e.g. `Application/MAIN`. GUIDs from `project-tree` may not match IDE GUIDs. |
| `update-pou --name NAME --st-path PATH [--app APP]` | Update one textual POU from an `.st` file. |
| `delete-pou NAME [--app APP]` | Delete a Program, Function, or Function Block. Permission-gated. |
| `read-log [--last N] [--clear]` | Read CODESYS IDE messages. |
| `permissions` | Show daemon permission settings. Read-only from CLI. |

Prefer `import` over `update-pou` for normal work. `update-pou` is an escape
hatch for single-object repairs.

## Visualization (SVG → CODESYS)

`cts visu` authors HMI screens as SVG and compiles them into CODESYS
visualization objects. The sketch is the source of truth; the compiled `.xml`
lands in `project-view/` and reaches the IDE through the normal `cts import`.

| Command | Meaning |
| --- | --- |
| `visu new --name NAME --w W --h H --out FILE` | Compose a laid-out SVG skeleton for that canvas size — header band, panels, KPI cards, bound field, action row. Not a fixed template: the layout is derived from `--w/--h`, and blocks that will not fit are dropped rather than squeezed. Verified lint-clean from 480×320 up, on sides that are multiples of 4; outside that the composition can collapse into itself or land off-grid, and `visu new` says so. |
| `visu lint --svg FILE [--fix] [--strict]` | Check the sketch for design problems: off-grid coordinates, text wider than its box, a font size outside the scale, a button too small to press, an unbound field, overlap, crowding. `--fix` snaps the mechanical ones in place, leaving comments and formatting intact. |
| `visu preview --svg FILE [--out PATH] [--grid N] [--no-png]` | Render the sketch with the colours the compiler will actually emit, as `<file>.preview.svg` + `.preview.png`. The sketch itself carries no colours, so this is the only way to see the screen before it is in the IDE. |
| `visu from-svg --svg FILE ...` | Compile the sketch into a screen `.xml`. Runs lint and writes a preview on the way through. |
| `visu to-svg --screen NAME` | Decompile an existing screen back to SVG. A dark screen comes back stamped `data-cds-scheme="dark"`, so recompiling reproduces it. |
| `visu check --screen NAME` | Validate a *compiled* screen (bounds, member consistency, Text-IDs). |
| `visu add / list / types / describe / create-screen` | Element-level operations on a compiled screen, without going through SVG. |

Flags shared by the SVG commands:

| Flag | Meaning |
| --- | --- |
| `--theme NAME` | CODESYS visual style to resolve colours against (default `flat-style`). `visu types` aside, every SVG command accepts it. |
| `--background auto\|style\|#RRGGBB` | Screen background. `auto` (default) uses the curated neutral; `style` restores the visual style's own. |
| `--scheme light\|dark` | Colour scheme. `visu new` records it on the sketch as `data-cds-scheme`, so the rest of the workflow needs no flag; on `lint`, `preview` and `from-svg` it overrides that attribute for a single run. On `to-svg` it overrides the scheme inferred from the screen's background. In `dark` the curated palette owns surfaces, text and native control colours — every shipped CODESYS style is a light style — so `--theme` stops affecting them. Lamps keep their indicator colours in both. |
| `--fix` | `lint` only: rewrite the mechanically fixable findings. |
| `--strict` | `from-svg` only: make lint findings fatal instead of advisory. |
| `--create-screen --screen-name NAME` | `from-svg` only: compile into a screen that does not exist yet, instead of `--screen`. Its placement in the project tree is copied from a sibling object in `--folder`, so the folder must already hold one. |
| `--replace` | `from-svg --create-screen` only: rebuild a screen that is already there. It keeps the existing object Guid — that Guid is the screen's identity on `cts import`, so a recompile updates the object CODESYS already has instead of adding a second screen beside it. Without the flag an existing screen is never overwritten. |
| `--no-preview` / `--no-png` | Skip the preview entirely, or write only the SVG. |
| `--grid N` | `preview` only: overlay an N-px grid as hairlines. |

`lint` and `preview` do not need a running daemon — they read the sketch and a
style, nothing else. They still ask a live daemon for the project view so a
project-level `visu.css` is picked up, but that lookup is brief and silent: with
no IDE running they simply proceed without one. Rasterisation uses a headless
Chrome/Edge if one is installed (`$CHROME_PATH` overrides the search); without a
browser the preview SVG is still written.

Colours are never written into a sketch. Elements carry a semantic
`class="panel|card|h1|value|ok|warn|alarm|pipe-water|metal|…"`, defined in
`cds_text_sync/visu/stylesheet.css` and overridable per project with a `visu.css` in the
project-view directory. See `skills/cds-visu-svg/SKILL.md` for the authoring
contract.

### `cts visu-lint`

A small machine-only validator for generated visualization XML:

```bash
cts visu-lint --xml screen.xml
```

| Flag | Meaning |
| --- | --- |
| `--xml FILE` | Generated visualization XML file to validate (required). |

It reports rule `VISU001`: an `ExplicitColor` literal in a colour member is
dead when a live `NamedColor` takes precedence — generated XML must not carry
both. Output is a single JSON object on `stdout` (`schema_version`, `ok`,
`findings`); exit code is `0` when clean, `1` when findings exist, `2` on an
unreadable input file.

## Raw And Engine Escape Hatches

The normal CLI should cover everyday use. These commands exist for compatibility
and debugging.

| Command | Meaning |
| --- | --- |
| `raw METHOD [--key value ...]` | Send a daemon method directly. Useful for overrides such as `force_online=true` or a custom `timeout`. |
| `rp METHOD [--key value ...]` | Deprecated alias for `raw`. |
| `engine export|import|compare|validate|resources|call-tree ...` | Run `engine_cli.py` directly without CODESYS. |

Examples:

```bash
cts raw help --timeout 10
cts raw application_tree --flat --output C:/Temp/tree.json --timeout 120
cts raw sync_import_text force_online=true --timeout 120
cts engine validate --project-root C:/Work/Project
cts engine call-tree --project-root ./MyProject --output call-tree.json
cts engine call-tree --project-root ./MyProject --snapshot .dump/IDE.xml --output call-tree.json
```

Raw daemon names are implementation details. Do not use them in new scripts
when a top-level command exists.

## Command Mapping

The simplified CLI maps to daemon methods as follows:

| CLI command | Daemon method |
| --- | --- |
| `ping` | `ping` |
| `status` | `status` |
| `export` | `sync_export_text` |
| `import` | `sync_import_text` |
| `compare` | `sync_compare_text` |
| `build` | `build` |
| `connect` | `connect_to_device` |
| `disconnect` | `disconnect_from_device` |
| `download` | `download` |
| `start` | `start_plc` |
| `stop` | `stop_plc` |
| `app-state` | `application_state` |
| `plc-crc` | `compare` |
| `read` | `read_variable` |
| `write` | `write_variable` |
| `test` | `cicd` |
| `analyze` | offline — no daemon method |
| `visu-lint` | offline — no daemon method |

## Timeouts

Always set explicit `--timeout` in scripts.

| Operation | Typical timeout |
| --- | --- |
| `ping`, `status`, `app-state`, `permissions` | 5-10s |
| `read`, `write`, `start`, `stop`, `disconnect` | 15-30s |
| `connect`, `compare`, `export` | 30-60s |
| `import`, `build`, `download`, `test`, snapshots | 120s |

## Error Handling

Successful commands print JSON data to `stdout`.

Failed commands print human-readable diagnostics to `stderr` and should exit
non-zero.

Common failures:

| Error | Meaning | Fix |
| --- | --- | --- |
| `Reverse pipe error: Timeout...` | Daemon is not running, busy, or blocked by a CODESYS dialog. | Check CODESYS and retry with a larger timeout. |
| `Not connected. Call connect_to_device first.` | Command needs an online PLC session. | Run `connect`. |
| `Forbidden by daemon settings` | Permission-gated command is blocked. | Change settings in the daemon dashboard. |
| `Invalid expression` | Variable is not exported to the online application. | Check symbol path/export settings. |
| `IMPORT.xml was not generated` | Disk state could not be converted into an import patch. | Run `compare`, inspect `.dump/compare_report.json`, then fix project-view. |

## Shell Notes

Use Windows Python when calling from WSL:

```bash
python.exe -m cds_text_sync.main status --timeout 10
```

If the installed command is not found, use the source form:

```bash
python -m cds_text_sync.main status --timeout 10
```
