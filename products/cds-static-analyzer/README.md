# cds-static-analyzer

Human-facing static analysis for exported CODESYS Structured Text (`.st`).
The analyzer is intentionally offline: it reads `project-view/` and does not
inspect CODESYS XML, connect to a daemon, or communicate with a PLC.

The implementation is in `src/cds_static_analyzer`. The repository CLI exposes
it as `cts analyze`; the optional desktop UI uses the same engine. The public
analyzer contract is separate from the sync engine and from visualization
linting.

## Install

From the repository or a release archive:

```powershell
python -m pip install .
cts analyze --help
```

The UI is optional:

```powershell
python -m pip install ".[ui]"
cts ui --workspace C:\path\to\sync-folder
```

`Project_analyze_ui.py` provides the CODESYS menu entry. It resolves the active
project's configured sync folder and starts the same offline UI; analysis still
uses only the exported `.st` files.

## From project to findings

The first analysis follows this export path:

1. Run `Project_directory.py` and choose the sync folder for the open project.
2. Run `Project_export.py`; the default profile already exports all supported
   `.st` and `.csv` text projections.
3. If a project has a custom profile or saved settings that disable `.st`,
   enable the projection in `Project_options.py` and export again.
4. Run `Project_analyze_ui.py` to open the findings UI for that export.

The analyzer is offline after export: it reads the `.st` files from
`project-view/` and does not need the daemon or a live project connection.

## Basic usage

```powershell
cts analyze --workspace C:\path\to\sync-folder
cts analyze --workspace C:\path\to\sync-folder --format json
cts analyze --workspace C:\path\to\sync-folder --format sarif
cts analyze rules
cts analyze explain CTS0001
cts analyze selftest
```

The workspace must contain `project-view/`, unless `--project-view` is passed
directly. JSON output is versioned and contains `schema_version`, `complete`,
`findings`, `diagnostics`, and `summary`. SARIF is suitable for CI and code
scanning integrations.

## Findings and policy

Rules are grouped into `danger`, `suspicious`, and `style`. The release includes
95 documented rules covering text, declarations, data flow, control flow,
types, pointers, strings, function blocks, and project structure. Rule
documentation is available through `cts analyze explain` and ships in the
package.

The analyzer distinguishes a rule finding from an analysis diagnostic. A run
with missing capabilities can be incomplete and is never silently reported as
clean. Use `--fail-on` and `--incomplete` to set CI policy. Exit codes are:

- `0` — policy passed;
- `1` — unsuppressed findings meet the failure threshold;
- `2` — configuration or startup error;
- `3` — incomplete analysis with `--incomplete=error`.

Baselines and suppressions are stored in `.cts-analyze/`, outside
`project-view/`. Suppressions require a reason. Safe autofixes, where
available, are previewed before anything is written.

The analyzer does not analyze visualization XML. That is handled by the
separate machine-oriented `cts visu-lint` product. The legacy XML/task
projection remains available only through the explicit
`cds_text_sync.analyze_compat` compatibility adapter and is not part of this
product's contract.
