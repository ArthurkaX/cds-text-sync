# `cts` Command Selection

Use this reference as a routing guide. Confirm exact syntax with the installed `cts --help` and `cts <command> --help`.

## Daemon and State

| Goal | Command |
|---|---|
| Check daemon liveness and cached PLC state | `cts ping` |
| Inspect daemon, project, sync folder, and PLC state | `cts status` |
| Read CODESYS IDE messages | `cts read-log` |
| Inspect daemon permissions | `cts permissions` |

## Folder and IDE Synchronization

| Goal | Command |
|---|---|
| Refresh projected files from the IDE | `cts export` |
| Compare the IDE with projected files | `cts compare` |
| Preview folder-to-IDE changes | `cts import --dry-run` |
| Apply folder-to-IDE changes | `cts import` |
| Compile the active application | `cts build` |

Disconnect before import when the IDE is online with the PLC. Import has no online override flag; it is refused until the IDE is offline.

## Project Inspection and Object Changes

| Goal | Command |
|---|---|
| Read project metadata | `cts project-info` |
| Read the object tree | `cts project-tree` |
| Read an object | `cts read-object` |
| Update one POU from Structured Text | `cts update-pou` |
| Delete a POU, function, or function block | `cts delete-pou` |

Prefer full folder import for coordinated source changes. Use object-level mutation only when its narrower scope is intentional.

## PLC Lifecycle

| Goal | Command |
|---|---|
| Connect or log in | `cts connect` |
| Disconnect or log out | `cts disconnect` |
| Download the application | `cts download` |
| Start or stop the application | `cts start`, `cts stop` |
| Read application state | `cts app-state` |
| Compare PLC and local build CRC | `cts plc-crc` |

Check the installed command help for whether download also starts the application; do not encode that behavior as version-independent.

## Variables

| Goal | Command |
|---|---|
| Read one expression | `cts read` |
| Write one expression | `cts write` |
| Read multiple expressions | `cts read-vars` |
| Build an offline variable map | `cts variable-map` |
| Capture online values | `cts variable-snapshot` |
| Preview or apply a restore | `cts variable-restore` |

Keep restore in dry-run mode unless the user explicitly requests application.

## Static Analysis

| Goal | Command |
|---|---|
| Run the offline analysis | `cts analyze` |
| List rules | `cts analyze rules` |
| Show one rule's docs | `cts analyze explain CTS0001` |
| Self-test rules | `cts analyze selftest` |
| Manage the baseline | `cts analyze baseline create\|update\|check` |
| Apply suppress/fix-later decisions | `cts analyze triage --apply decisions.json` |
| Validate generated visu XML | `cts visu-lint --xml file.xml` |

`cts analyze` runs offline over `project-view/` — it never talks to the daemon.
`--rule CTSxxxx` restricts to one rule (repeatable); `--fail-on` sets the exit-1
threshold (`danger`/`suspicious`/`style`); `--incomplete error` makes partial
runs exit 3. Exit codes: 0 passed, 1 findings at/above `--fail-on`, 2 config or
startup error, 3 incomplete. Some rules are opt-in and disabled by default. The
`cts-analyze.toml` config sets `[analyze] fail_on`/`incomplete`, `[rules.<ID>]
enabled`/`severity`/`options`, and `[[rule_scope]]`. State lives in
`.cts-analyze/` (baseline.json, suppressions.toml, session.json); source files
opt out with `// cts:ignore-file CTS0001 -- reason`.

## Tests, Offline Engine, and Escape Hatch

| Goal | Command |
|---|---|
| Run JSON test plans | `cts test` |
| Run offline engine operations | `cts engine` |
| Call a daemon method directly | `cts raw` |

Inspect nested help before using these commands. Use `raw` only when the normal CLI does not expose the required supported operation.

## Output

- Default output is JSON and is suitable for parsing.
- Use `--pretty` or `--output text` for concise human-readable output.
- Preserve raw error details when reporting failures.
