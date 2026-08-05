# Product boundaries and staged repository refactor

The repository contains several products with different runtimes and users.
They must be separated by directory and package boundaries without changing
their observable behaviour during the migration.

## Current product boundaries

The intended top-level structure is:

```text
products/
  cds-text-sync/
    src/cds_text_sync/

  cds-static-analyzer/
    src/cds_static_analyzer/

  cds-cli/
    src/cds_cli/

  codesys-host/
    entrypoints/
      Project_*.py
    ide_bridge/
```

The products have these responsibilities:

* `cds-text-sync` — synchronization libraries for Structured Text, project
  folders, XML projections, manifests, diffs, and the external engine.
* `cds-static-analyzer` — the human-facing analyzer for `.st` files only. It
  must not depend on CODESYS XML or `ide_bridge`.
* `cds-cli` — the user-facing command-line composition layer. It may depend on
  product libraries but should contain little domain logic.
* `codesys-host` — code executed inside CODESYS, including `Project_*.py`,
  `ide_bridge`, and the bootstrap/runtime compatibility layer. It must remain
  isolated from the normal CPython CLI and analyzer runtime.
* `visu-lint` — a separate machine/LLM feedback product for visualization XML;
  it must not be registered as a static-analyzer rule or merged into the `.st`
  analyzer contract.

Directory names may use hyphens for products; Python import packages use
underscores. A product does not have to become independently publishable on
the first migration step, but its source and dependency boundary must be
visible in the tree.

## Migration rules

The refactor is staged. Each stage must preserve the existing CLI entrypoints,
CODESYS deployment names, analyzer finding contracts, and test behaviour.

Do not begin by rewriting imports globally. First move files with compatibility
shims or explicit path configuration, then change imports after the new
boundary is covered by tests.

The CODESYS host tree is a special runtime boundary: it is loaded by CODESYS/
IronPython and may not import ordinary CPython-only packages. Existing root
discovery and bridge import behaviour must either be preserved or replaced by
an explicitly tested equivalent.

## Staged implementation

### Stage 1 — isolate CODESYS host files — done

Move `Project_*.py`, `cds_bootstrap.py`, and `src/ide_bridge/` under
`products/codesys-host/`. Preserve the deployable `Project_*.py` names and add
a packaging/deployment mechanism if CODESYS requires them at a flat location.
Update root discovery, bridge import tests, regression paths, and
documentation.

Acceptance criteria:

* all existing unit and regression tests pass;
* every CODESYS entrypoint remains discoverable under its original name;
* no host module imports `cds-cli` or the static analyzer;
* the normal CPython package does not depend on the host directory being on
  `sys.path`.

### Stage 2 — extract `cds-static-analyzer` — done

Move `cds_text_sync.analyze` and its rule resources into a dedicated
`cds_static_analyzer` package. Preserve rule IDs, finding JSON, suppressions,
baselines, CLI output, and `.st`-only scope. The analyzer must not import
visualization or CODESYS-host modules.

### Stage 3 — extract `cds-cli`

Move command parsing and dispatch into `cds_cli`. Keep `cts` and
`cds-text-sync` command entrypoints working through compatibility wrappers while
the migration is in progress. CLI handlers delegate to product APIs instead of
becoming a new location for synchronization or analyzer logic.

### Stage 4 — separate visualization tooling

Define the boundary between visualization support used by text synchronization
and the independent `visu-lint` product. Low-level XML helpers may be shared
when runtime-neutral. Analyzer registries, finding schemas, suppressions, and
baselines must not be shared with `visu-lint`.

### Stage 5 — packaging and test topology

Give each product an explicit build configuration and test ownership. Verify
that a distribution for one product does not accidentally include another
product's runtime files. Add a clean-tree packaging check to the release
procedure.

## Status

Stage 1 is complete. The CODESYS host product now lives under
`products/codesys-host/` with the original `Project_*.py` names and the
`src/ide_bridge` flat-module layout preserved inside that product. Bootstrap,
menu installation, engine discovery, CLI daemon launching, CI compilation, and
tests were updated accordingly.

Stage 2 is complete. The analyzer source and rule resources now live under
`products/cds-static-analyzer/src/cds_static_analyzer/`; `cts analyze` and the
desktop analyzer UI use that package. Source-checkout path setup and wheel
package discovery keep the migration compatible with the existing CLI.

Clean-wheel installation, analyzer selftest, full unit tests, Ruff, and the
legacy-reference scan all pass. The next implementation task is Stage 3:
extract the CLI composition layer into `cds-cli`.
