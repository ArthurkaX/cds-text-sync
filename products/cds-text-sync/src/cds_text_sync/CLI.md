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
| `export` | IDE -> disk | Export the open IDE project and refresh `project-view/`; locally modified files are kept by default. | 300s |
| `compare` | IDE vs disk | Compare the open IDE project against `project-view/`. | 300s |
| `import` | disk -> IDE | Build `IMPORT.xml` from `project-view/` and apply it to the IDE project. | 600s |

Normal edit cycle:

```bash
cts export --timeout 60
# edit files in project-view/
cts compare --timeout 60
cts import --timeout 120
cts build
```

`import` options:

| Flag | Meaning |
| --- | --- |
| `--dry-run` | Show what would change without applying (runs compare). |
| `--save` | Save the project after applying. Off by default. |
| `--no-refresh` | Skip the post-import re-baseline of `project-view/` and `manifest.json`. |

Rules:

- `export` refreshes `project-view/` from the IDE state, but the daemon keeps
  locally modified files and reports them as `pending_import` by default. This
  prevents an export from silently discarding edits that have not been
  imported yet.
- `import` treats disk as the source of truth.
- `import` does **not** save the project. Everything it does — creating
  objects, updating bodies, applying the structured view — happens in the
  in-memory project, exactly as if you had typed it in the IDE. Saving also
  commits whatever else you have open, so it stays your decision: press Ctrl+S
  in the IDE, or pass `--save`. Until then the response carries an `unsaved`
  warning, and closing or reloading the project discards the import.
- `--save` also takes a binary backup into `.backup/` first, the same one the
  manual `Project_import` action takes. Without `--save` there is nothing to
  back up — the `.project` file on disk is never written, so it already is the
  pre-import state.
- `import` re-baselines the disk afterwards. `manifest.json` is the only record
  of which files are managed, and only an export writes it, so without this
  step `compare` keeps reporting the changes you just imported and the next
  `import` re-applies them. The refresh regenerates view files from the live
  in-memory project — a save is not a precondition — so it is withheld only
  when something did not reach the IDE at all: a failed create, or a projection
  that could not be applied. In those cases the response carries
  `manifest_refresh_skipped` with the reason, and the affected file on disk is
  left alone because it holds the only copy of that edit.
- `import` cannot delete. An object that exists in the IDE but not in
  `project-view/` is written back to disk by the refresh; delete it in the
  CODESYS IDE instead. The response says so in `manifest_refresh_restored`.
- `import` is refused whenever the IDE is connected to a PLC/runtime. Run
  `disconnect` first; there is no override because applying an offline project
  patch while online can silently fail to create objects.
- `build` compiles in the IDE only. It does not guarantee that the PLC is
  running the new code.

## Build And PLC Commands

| Command | Meaning | Requires | Timeout |
| --- | --- | --- | --- |
| `build` | Compile the active application in the IDE. | daemon | automatic |
| `connect [--ip IP]` | Login/connect to the configured PLC or explicit IP. | daemon + device | automatic |
| `disconnect` | Logout from the PLC. | daemon | automatic |
| `download [--start 0|1]` | Force a full download to PLC. Use after adding new objects. | online/device | automatic |
| `start` | Start PLC application. | online | automatic |
| `stop` | Stop PLC application. | online | automatic |
| `app-state` | Show application run/stop/login state. | daemon | automatic |
| `plc-crc` | Compare PLC `Application.crc` with the local IDE build output. | online | automatic |

The daemon counts `project-view/*.st` once at startup and exposes a
per-operation timeout profile. Every daemon-backed CLI command uses that
profile unless `--timeout SECONDS` is supplied explicitly.

Deploy existing online-changeable edits:

```bash
cts import
cts build
cts connect
cts plc-crc
```

Deploy newly added objects:

```bash
cts disconnect
cts import
cts build
cts download
cts plc-crc
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

## Sharing Changes (`cts patch save`)

`cts patch save` packages the text you changed on disk so a colleague working on
the same project can copy it in. It runs a compare against the open IDE, then
copies only the hand-authored text into a folder that mirrors the project
structure:

- every changed `.st` and `.csv` projection;
- the XML of objects whose kind is listed in `xml_in_view_kinds` (visualizations
  by default), because that XML is edited by hand.

Everything else the project view owns — device descriptions, task configuration,
the library manager — is left out on purpose: it encodes the sending machine's
state, and copying it across machines is what makes untouched visu objects show
up as modified.

```bash
cts patch save                       # -> .dump/patch/patch_<UTC timestamp>/
cts patch save --out D:\share\fix    # somewhere else
cts patch save --zip                 # also write <folder>.zip
cts patch save --dry-run             # list what would be packaged
```

Result:

```text
.dump/patch/patch_20260809-143512/
├─ project-view/
│  ├─ Application/PLC_PRG.st
│  └─ HMI/Visu/Main.xml
├─ patch.json
└─ README.txt
```

| Flag | Meaning |
| --- | --- |
| `--out DIR` | Output folder (default `<sync-folder>/.dump/patch/patch_<UTC>`). |
| `--sync-folder DIR` | Use this sync folder instead of asking the daemon. |
| `--zip` | Also write `<output folder>.zip`. |
| `--dry-run` | List what would be packaged; write nothing. |
| `--bare` | Write only the files, without `patch.json` and `README.txt`. |

On the receiving side no extra command is needed:

```bash
# copy project-view/ from the patch over your own sync folder root, replacing files
cts compare --timeout 60
cts import --timeout 120
```

Deleted objects cannot be shipped as files. They are listed in `patch.json` and
in `README.txt` so the receiver can remove them by hand.

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

## FSM Transition Maps (`cts fsm`)

`cts fsm` scans the exported `project-view/` tree for state machines and
renders them offline. Like `cts analyze`, it never talks to the daemon and
never reads `.dump/`, so it works with no CODESYS running. All three
subcommands share the same exit-code contract: `0` means the command produced
its output, `2` means it could not run. `1` is deliberately never used here —
in this repository it already means "the analysis found something"
(`cts analyze` exits `1` on findings), so "nothing found" is reported in the
payload, never through the exit status.

| Subcommand | Meaning |
| --- | --- |
| `fsm scan [options]` | Scan the workspace and report every machine found. |
| `fsm show [options]` | Render one file's machine as JSON, mermaid, or SVG. |
| `fsm ui [options]` | Open the local FSM map window. |

`cts fsm scan`:

| Flag | Meaning |
| --- | --- |
| `--workspace DIR` | Sync folder containing `project-view/` (required). |
| `--query TEXT` | Only scan files whose relative path contains this case-insensitive substring. |
| `--workers N` | Worker process count (default: `min(6, cpu_count)`). |
| `--json` | Emit exactly one JSON document to stdout. |

By default `scan` prints one human-readable line per matching file plus a
summary line; diagnostics go to stderr. With `--json`, stdout carries exactly
one JSON document (`workspace`, `source_root`, `snapshot`, `counts`,
`results`). A scan that finds zero FSMs still exits `0`.

`cts fsm show`:

| Flag | Meaning |
| --- | --- |
| `--workspace DIR` | Sync folder containing `project-view/` (required). |
| `--file RELATIVE_PATH` | Path relative to `project-view`, e.g. `Application/PLC_PRG.st` (required). |
| `--machine INDEX` | Machine index in the file (default: `0`). |
| `--format json\|mermaid\|svg` | Output format (default: `json`). |

`--file` is always resolved relative to `project-view/`; a path that escapes
the source root is rejected. A valid ST file with no FSM is still a successful
run: with `--format json` the payload reports the empty machine list, for
mermaid/svg the absence goes to stderr, and the exit code stays `0`.

`cts fsm ui`:

| Flag | Meaning |
| --- | --- |
| `--workspace DIR` | Sync folder containing `project-view/` (optional; omitted opens the folder picker). |
| `--project-file PATH` | CODESYS project file path, accepted for the CODESYS launcher; unused for now. |

The UI is an optional dependency: `pip install 'cds-text-sync[ui]'`. The window
is non-modal and scans in a bounded worker pool, so the interface stays
interactive while a large function block is analysed.

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Output produced — including a scan with zero FSMs and a file with no machine — or, for `ui`, the window opened and closed normally. |
| `2` | Invalid workspace, invalid/traversing path, bad machine index, read/parse failure, or (for `ui`) a startup failure or missing pywebview dependency. |

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
| `raw METHOD [--key value ...]` | Send a daemon method directly. Useful for diagnostic parameters or a custom `timeout`. |
| `rp METHOD [--key value ...]` | Deprecated alias for `raw`. |
| `engine export|import|compare|validate|resources|call-tree ...` | Run `engine_cli.py` directly without CODESYS. |

Examples:

```bash
cts raw help --timeout 10
cts raw application_tree --flat --output C:/Temp/tree.json --timeout 120
cts raw sync_import_text --timeout 120
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
| `patch save` | `sync_compare_text` (then local file copying) |
| `analyze` | offline — no daemon method |
| `fsm scan/show/ui` | offline — no daemon method |
| `visu-lint` | offline — no daemon method |

## Timeouts

Always set explicit `--timeout` in scripts.

`export`, `compare`, and `import` scale with project size, not with the size of
your edit. `import` exports a fresh IDE snapshot, then runs the engine over it
twice (once to build `IMPORT.xml`, once to build the compare report that
carries modified POU bodies), applies the result, and then re-baselines the
disk with a full export. On a ~70 MB snapshot that is 4-5
minutes for a one-line change. The defaults below allow for that; `--no-refresh`
drops the last step and roughly halves it, at the cost of leaving `compare`
reporting the change you just imported.

A CLI timeout only stops the CLI from waiting. The daemon keeps executing the
command, so the IDE can still change after the error. Retry with a larger
`--timeout` rather than treating the first timeout as a failed import.

| Operation | Typical timeout |
| --- | --- |
| `ping`, `status`, `app-state`, `permissions` | 5-10s |
| `read`, `write`, `start`, `stop`, `disconnect` | 15-30s |
| `connect`, `download`, `test`, snapshots | 60-120s |
| `build` | 120s |
| `export`, `compare` | 300s |
| `import` | 600s |

## Error Handling

Successful commands print JSON data to `stdout`.

Failed commands print human-readable diagnostics to `stderr` and should exit
non-zero.

Common failures:

| Error | Meaning | Fix |
| --- | --- | --- |
| `Reverse pipe error: Timeout...` | Usually the command is still running, not hung: the sync trio scales with project size. The CLI giving up does not cancel it. | Retry with a larger `--timeout`. Only suspect a real hang if `cts ping` also stops answering. |
| `Not connected. Call connect_to_device first.` | Command needs an online PLC session. | Run `connect`. |
| `Forbidden by daemon settings` | Permission-gated command is blocked. | Change settings in the daemon dashboard. |
| `Invalid expression` | Variable is not exported to the online application. | Check symbol path/export settings. |
| `IMPORT.xml was not generated` | Disk state could not be converted into an import patch. | Run `compare`, inspect `.dump/compare_report.json`, then fix project-view. |

## Shell Notes

Use Windows Python when calling from WSL:

```bash
python.exe -m cds_cli.main status --timeout 10
```

If the installed command is not found, use the source form:

```bash
python -m cds_cli.main status --timeout 10
```
