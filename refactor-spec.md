# Refactor Spec — Technical Debt Review

**Scope:** god files, DRY violations, adequate decomposition level.
**Repo:** `cds-text-sync` @ `c6dd834`
**Method:** static inventory (`git ls-files`, `wc -l`), AST measurement of function/class
extents, body-level diffs of suspected duplicates, reachability tracing of dispatch
branches. Every claim below cites `file:line` and a measured number. No finding is
based on naming similarity alone.

---

## 0. Context that shapes every recommendation

The repo is **mid-migration**. Recent history (`refactor: define product packaging
boundaries` → `refactor: isolate visu lint product` → `refactor: isolate CLI product`)
shows a deliberate split into `products/`:

| Product | Files (non-test) | LOC |
|---|---:|---:|
| `cds-text-sync` | 58 | 19 080 |
| `codesys-host` | 35 | 15 027 |
| `cds-static-analyzer` | 94 | 11 598 |
| `cds-cli` | 9 | 2 612 |
| `visu-lint` | 3 | 98 |

**The split is correct and should be finished, not reversed.** A large share of the
debt below is *migration residue* — compat shims kept alive by tests, stale config
pointing at pre-split paths, ownership manifests that were never re-partitioned. Those
are cheap to clear and should go first, because they currently mask the real
structural problems.

The second shaping fact: `codesys-host/src/ide_bridge/` runs under **IronPython inside
the CODESYS IDE**. It cannot be imported by CI, cannot be unit-tested normally, and
cannot use modern syntax. That is a real constraint — but it is currently being used
to excuse things it does not justify (see §C.4, §D.2).

---

## 1. Executive summary

| # | Finding | Axis | Severity | Effort |
|---|---|---|---|---|
| A.1 | `build_parser` is a single **858-line function** | god | High | M |
| A.2 | `project_snapshooter.py` — 1611 lines, ~900 of them WinForms UI | god / decomp | High | L |
| A.3 | `FolderWriter` 717 lines/31 methods, `FolderReader` 651/21 | god | High | L |
| A.4 | `visu/commands.py` — 1432 lines, library + CLI + presentation fused | god / decomp | High | M |
| A.5 | `ProjectOptionsForm.__init__` — 276 lines | god | Med | M |
| B.1 | ST declaration parser exists **twice**, function-for-function | DRY | High | M |
| B.2 | Comment/pragma blanking duplicated **and divergent** — latent bug | DRY | **Critical** | S |
| B.3 | Command vocabulary has **4 sources of truth** | DRY | High | M |
| B.4 | **Three** renderers over the same visu element vocabulary | DRY | Med | L |
| B.5 | `svg_import.parse_svg` — half table-driven, half copy-pasted branches | DRY | Med | S |
| C.1 | 37 `sys.exit()` calls inside a library module | decomp | High | S |
| C.2 | 439 `except Exception` in `codesys-host` | decomp | High | L |
| C.3 | Flat imports force 20 `sys.path` mutations across 16 modules | decomp | Med | M |
| C.4 | `offline_regression.py` — 1552-line runner outside pytest | decomp | Med | M |
| D.1 | ~300 lines of provably dead visu render path | dead | Med | S |
| D.2 | CI compile step is a **silent no-op**; bridge never compiled | guardrail | **Critical** | S |
| D.3 | Product test ownership is wrong and unenforced | guardrail | High | S |
| D.4 | 12 compat shims kept alive only by tests importing legacy paths | dead | Med | S |

---

## Part A — God files

### A.1 `build_parser` — an 858-line function

`products/cds-cli/src/cds_cli/_cli_parser.py:17`

The single worst offender in the repo: **858 lines in one function**, 874 in the file.
It contains ~26 `add_parser` calls plus nested helper closures (`add_timeout`,
`add_daemon_parser`, `add_analyze_common`) defined inline and reused by position in the
body. There is no way to test one subcommand's argument surface in isolation, and any
change to any command touches the same function.

**Target:** one module per command group under `cds_cli/parsers/`, each exposing
`register(subparsers) -> None`. `build_parser` becomes a ~30-line loop over a registry
list. Shared fragments (`add_timeout`, `add_analyze_common`) become module-level
functions in `cds_cli/parsers/_common.py`.

This also unblocks B.3 — a registry is exactly the single source of truth the command
vocabulary is missing.

### A.2 `project_snapshooter.py` — domain logic fused with 900 lines of WinForms

`products/codesys-host/src/ide_bridge/project_snapshooter.py` — 1611 lines.

- `_run_winforms_interactive` (`:1127`) — **473 lines**, the largest function outside `build_parser`
- `class SnapshooterForm` (`:1166`) — **427 lines, 29 methods**

Together ~900 lines of presentation sitting in the same module as snapshot creation,
comparison, retention, and restore logic. The domain half is pure computation and would
be testable in CPython — but it is welded to `clr.AddReference("System.Windows.Forms")`
and therefore currently untestable in CI.

**Target:** split into `project_snapshooter.py` (pure: create/compare/retain/restore,
importable without CLR) and `project_snapshooter_ui.py` (WinForms only). The pure half
becomes a CI-testable unit; the UI half stays IronPython-only. This is the highest-value
single split in the repo — it converts ~700 lines from "untestable by construction" to
"ordinary Python".

### A.3 `FolderWriter` / `FolderReader` — the engine's two god classes

| Class | Lines | Methods | Worst method |
|---|---:|---:|---|
| `FolderWriter` (`engine/folder_writer.py:90`) | 717 | 31 | `write` 132, `_write_projection_files` 95, `_remove_orphan_projection_files` 53 |
| `FolderReader` (`engine/folder_reader.py:99`) | 651 | 21 | `read` **176**, `_discover_pending_xml_creates` 90, `_discover_pending_st_creates` 78 |
| `PatchBuilder` (`engine/_patch_builder.py:36`) | 454 | 16 | `build_patch` 173 |

Each class carries at least three separable responsibilities: filesystem layout
resolution, projection (`.st`/`.csv`) encode/decode, and manifest/hash bookkeeping.
`FolderReader.read` at 176 lines interleaves all three plus pending-create discovery.

**Target:** extract `ProjectionCodec` (st/csv ↔ xml, both directions — currently split
across writer and reader), `LayoutResolver` (view-root/sync-mode path rules), and
`ManifestBookkeeper` (hashes, orphan detection). Writer and reader become thin
orchestrators over the three. Note the codec extraction is shared between both classes —
it removes duplication as well as size.

### A.4 `visu/commands.py` — 1432 lines, three concerns

`products/cds-text-sync/src/cds_text_sync/visu/commands.py`

- `compose_skeleton` (`:463`) — 179 lines
- `from_svg` (`:1075`) — 160 lines
- **37 `sys.exit()` calls** and `_err`/`_ok`/`_warn` printing to stderr — see §C.1

Library orchestration, CLI argument validation, and terminal presentation are
interleaved throughout. The `sys.exit` calls make it unusable as a library.

### A.5 `ProjectOptionsForm.__init__` — 276 lines

`products/codesys-host/src/ide_bridge/codesys_ui.py:294` (class at `:288`, 484 lines/17
methods). A single constructor building the entire options dialog: control
construction, layout arithmetic, event wiring, and initial state load.

`codesys_ui.py` also hosts `CompareResultsForm` (`:787`, 300 lines/18 methods) — 1107
lines total.

**Target:** `__init__` builds sections via `_build_<section>()` helpers returning
panels; state load moves to an explicit `load_from(options)`.

### A.6 Remaining size hotspots (measured, lower priority)

```
1120  ide_bridge/ide_apply_patch.py
1118  visu/lint.py
1107  ide_bridge/codesys_ui.py
1067  visu/svg_import.py
1064  ide_bridge/ide_online_helpers.py
1059  ide_bridge/ide_handlers_sync.py       (_cmd_sync_import_text = 255 lines)
 974  engine/xml_helpers.py
 961  engine/call_tree.py                  (_resolve_calls = 183 lines)
 916  ide_bridge/ide_handlers_project.py   (_cmd_probe_oa = 176 lines)
```

Plus, in tests: `test_rules.py` 2366, `test_visu_builder.py` 2313.

---

## Part B — DRY violations

*These were confirmed by diffing bodies, not by matching names.*

### B.2 (listed first — it is the only correctness bug) Divergent blanking

`cds_static_analyzer/st/blanking.py` states the duplication in its own docstring:

> *"These mirror the engine's `variable_map._blank_noise` and
> `call_tree._trim_string_literals` without dragging the flat-import engine modules
> into the analyzer."*

The two copies **have already drifted**. The analyzer's pragma handler does not track
nesting:

```python
# cds_static_analyzer/st/blanking.py — non-nesting
if c == "{":
    while i < n and text[i] != "}":
        out.append("\n" if text[i] == "\n" else " ")
        i += 1
```

while the engine's does:

```python
# engine/call_tree.py:110 _blank_comments — depth-tracking
if c == "{":
    depth = 1
    out.append(" "); i += 1
    while i < n and depth > 0:
        if text[i] == "{": depth += 1
        elif text[i] == "}": depth -= 1
        out.append("\n" if text[i] == "\n" else " ")
        i += 1
```

**Consequence:** on a nested pragma such as `{attribute 'x' := '{y}'}`, the analyzer
stops blanking at the inner `}` and treats the trailing `}` plus following text as live
code. Every rule operating on blanked text can misfire on that input — and because the
analyzer's whole point is diagnostics, the failure mode is false positives or missed
findings, silently.

**This is not merely duplication. It is a live divergence in a correctness-critical
primitive.** Fix first, independently of everything else.

**Target:** one implementation. The analyzer is the natural home (it has no engine
dependency and is the stricter consumer); the engine imports from it. If the dependency
direction is unacceptable, extract to a shared `st_text/` module both depend on — but
*one* implementation either way, with the depth-tracking semantics, and a test pinning
nested-pragma behaviour.

### B.1 The ST declaration parser exists twice

`engine/variable_map.py` (850 lines) and `cds_static_analyzer/st/declarations.py`
(263 lines) implement the **same eight functions**:

`_split_top_level`, `_split_statements`, `_parse_member_statement`, `parse_var_blocks`,
`parse_dut`, `_base_type_name`, `classify_type`, `_split_dims`

— plus `SCALAR_TYPES`, defined twice (`variable_map.py:41` as `set`,
`declarations.py:15` as `frozenset`). The regexes are character-identical:

```python
r"(?i)^(W?STRING)\s*(\(.*\)|\[.*\])?\s*$"
r"(?is)^ARRAY\s*\[(.*?)\]\s*OF\s+(.+)$"
```

The differences are cosmetic (type annotations, `frozenset` vs `set`, generator vs list).
Semantically the two are the same parser, maintained in parallel — which means every IEC
declaration edge case must be fixed twice, and B.2 proves that in practice it isn't.

**Target:** same as B.2 — `declarations.py` is the canonical copy; `variable_map.py`
keeps only the engine-specific concerns (offset preservation for write-back, XML
integration) and imports parsing. Sequence B.2 first so both land on the same blanking
primitive.

### B.3 The command vocabulary has four sources of truth

| Source | Location | Entries |
|---|---|---:|
| Dispatch table | `ide_bridge/ide_reverse_pipe_loop.py` `_DISPATCH` (+ `_ALIASES`, `_NO_PERMISSION`) | ~55 |
| Help text | `ide_bridge/ide_handlers_project.py:423` `_cmd_help` | ~52 |
| CLI parser | `cds_cli/_cli_parser.py:17` `build_parser` | ~26 subparsers |
| CLI dispatch | `cds_cli/main.py` if/elif chain + 30-entry `__all__` | ~30 |

`_cmd_help` is a hand-maintained list of command→description strings that duplicates
`_DISPATCH`'s keys with no mechanical link. Adding a command means four edits; forgetting
one produces a command that exists but isn't documented, or is documented but doesn't
exist — with no test that can catch either.

**Target:** one declarative registry (name, aliases, permission flag, help text, parser
builder). `_DISPATCH` and `_NO_PERMISSION` derive from it; `_cmd_help` renders from it;
`build_parser` iterates it (this is exactly the A.1 target). A test asserts the bridge's
command set equals the CLI's.

The registry must live where **both** IronPython and CPython can read it. A plain data
module (dicts and strings, no imports) in the shared package satisfies both.

### B.4 Three renderers over the same element vocabulary

| Module | Direction | Dispatch |
|---|---|---|
| `visu/builder.py` | spec → CODESYS XML | catalog + `golden_template` |
| `visu/svg_export.py:973` `_element_to_svg` | CODESYS XML → SVG | **11-branch** if/elif |
| `visu/preview.py:220` `_render_element` | spec → SVG | 7-branch if/elif |

`_element_to_svg` branches over `VisuFbElemSimple / VisuFbElemLine / VisuFbLabel /
VisuFbElemButton / VisuFbElemTextfield / VisuFbElemLamp / VisuFbImageSwitcher /
VisuFbComboBoxInteger / VisuFbElemAlarmBanner / VisuFbFrame / VisuFbElemSlider`;
`preview._render_element` branches over `rectangle|line|label|button|textfield|lamp|else`.

Adding an element type requires touching three modules that share no table. The
geometry/colour handling per element is re-derived in each.

**Target:** a single element-type descriptor table (type name ↔ catalog ↔ SVG shape ↔
geometry accessor), with the three renderers reduced to table lookups + per-direction
emit functions. Lowest-risk first step: merge `preview._render_element` into
`svg_export` (both emit SVG; they differ only in input shape).

### B.5 `parse_svg` — half table, half copy-paste

`visu/svg_import.py:898`. Six near-identical promotion blocks precede a
`_ELEMENT_PARSERS` dict:

```python
if tag == "rect" and child.get("data-cds-type") == "lamp":
    elements.append(_parse_lamp(child, merged_theme))
    _apply_dialog_attrs(child, elements[-1])
    continue
```

The table already exists. The six blocks exist because `data-cds-type` promotion wasn't
folded into the key.

**Target:** key `_ELEMENT_PARSERS` on `(tag, data-cds-type or None)`, delete the six
blocks. Small, mechanical, well covered by existing round-trip tests.

### B.6 Colour resolution spread across three modules

`visu/style_roles.py` (role → CanonicalName anchors), `visu/themes.py` (`_STYLE_ROLES`
literal hex map), `visu/styledef.py` (sampled from real `styledef.xml`). `themes.py`
imports `style_roles` but *also* keeps its own hardcoded role→hex dict.

Not a clean duplication — the layering is defensible — but the fallback hex values are
maintained in two places. Worth a consolidation pass after B.4; low priority.

---

## Part C — Adequate decomposition level

### C.1 A library module that calls `sys.exit` 37 times

`visu/commands.py`:

```python
def _err(msg): print("[ERROR] {0}".format(msg), file=sys.stderr)
...
if not (screen or "").strip():
    _err("No screen given: pass --screen <name> ...")
    sys.exit(1)
```

37 `sys.exit(` calls plus direct stderr writes in a module imported as a library. Any
caller wanting to handle a validation failure — the daemon, a test, another command —
cannot. The process dies.

**Target:** raise `VisuCommandError(message, exit_code)`; the CLI layer catches and
translates to exit code + stderr. Mechanical, ~37 sites, immediately testable. This is
the single highest ratio of value to risk in Part C.

### C.2 439 `except Exception` in `codesys-host`

| Product | `except Exception` (non-test) |
|---|---:|
| `codesys-host` | **439** |
| `cds-text-sync` | 47 |
| `cds-static-analyzer` | 10 |
| `cds-cli` | 6 |

Concentrated in: `ide_handlers_project.py` 54, `ide_online_helpers.py` 49,
`project_snapshooter.py` 30, `ide_daemon_helpers.py` 30, `ide_handlers_sync.py` 29,
`ide_handlers_plc.py` 29, `ide_apply_patch.py` 29, `ide_handlers_crc.py` 27. 180 of the
bridge's handlers are `except: pass`-shaped.

Some of this is legitimate — the CODESYS Script Engine throws opaque .NET exceptions and
a crashed bridge takes the IDE with it. But at 439 sites it is no longer a defensive
boundary, it is the default control flow. A failing operation is indistinguishable from
a succeeding one, which is why bridge bugs surface as "nothing happened".

**Target:** not a blanket rewrite. Establish **one** top-level catch per command handler
that logs with context and returns a structured error, then delete the inner swallows in
the 8 hotspot files. Where an inner catch is genuinely needed, require a log line — a
lint rule can enforce "no `except Exception` whose body is only `pass`/`continue`".

### C.3 Flat imports force `sys.path` mutation

`engine/` has 22 modules importing each other flat (`from _project_model import ...`,
28 such imports) with `engine/__init__.py` being a single comment line. This forces
**20 `sys.path.insert/append` sites across 16 non-test modules**: 11 in `codesys-host`,
3 in `cds-cli`, 2 in `cds-text-sync`.

Import order becomes load-bearing — hence the `E402` ruff exemptions and hence
`tests/unit/test_bridge_import_order.py` and `test_daemon_name_resolution.py` existing
at all (the latter is a static guard against missing-import `NameError`s, i.e. a test
that exists purely to compensate for the import style).

The IronPython constraint justifies flat imports **inside `ide_bridge/`**. It does not
justify them in `engine/`, which runs under CPython 3.11.

**Target:** convert `engine/` to relative imports (`from ._project_model import ...`),
drop the corresponding `sys.path` mutations and `E402` exemptions. Leave `ide_bridge/`
alone. Expect this to delete several of the 20 sites and simplify the two guard tests.

### C.4 The regression suite is outside pytest

`tests/regression/offline_regression.py` — 1552 lines, 22 `_scenario_*` functions, its
own `RegressionFailure` exception and `main()`. `regression_suite.py` shells out to it
and two siblings via subprocess.

A hand-rolled runner means: no `-k` selection, no fixtures, no parametrization, no
per-scenario reporting in CI, and no shared setup with the 49 unit tests.
`requirements-dev.txt` is exactly `pytest>=7.0,<10` — the tool is already there.

**Target:** each `_scenario_*` becomes a pytest test (mechanical — they are already
independent, no-argument functions); `RegressionFailure` becomes `assert`.
`regression_suite.py` becomes a pytest marker. Do this after the shim cleanup (D.4) so
the tests being converted are already importing canonical paths.

### C.5 Presentation fused into domain modules

Recurring pattern, three instances: `project_snapshooter.py` (A.2), `codesys_ui.py`
(A.5), `visu/commands.py` (C.1). In each case a module that computes something also
decides how to display it and, in the `commands.py` case, whether the process lives.

This is the root cause behind A.2, A.4, A.5 and C.1 — worth naming explicitly so the
splits are done consistently: **domain modules return values; edge modules print and
exit.**

---

## Part D — Dead weight and stale guardrails

### D.2 (listed first — it is a live CI hole) The compile step is a no-op

`.github/workflows/ci.yml`:

```yaml
- name: Compile Python sources
  run: |
    python -m compileall `
      products/codesys-host/cds_bootstrap.py `
      products/codesys-host/Project_*.py ... `
      cds_text_sync `
      src
```

`src/` **does not exist** — it was moved to `products/*/src/` by the migration.
Verified: `python -m compileall src` prints `Can't list 'src'` and **exits 0**. The step
is green and checks nothing for that path.

Worse: `products/codesys-host/src/ide_bridge/` — 35 modules, 15 027 lines, the
IronPython code CI *cannot otherwise exercise at all* — is never compiled. Syntax errors
in the bridge reach the IDE.

**Target:** point `compileall` at `products/codesys-host/src/ide_bridge` and the product
source roots; drop `src`. Add `-q` and confirm a deliberately broken file fails the job.
**Do this first — it is a one-line fix that restores the only check the bridge has.**

Related stale config, `pyproject.toml:69`:

```toml
"src/ide_bridge/*.py" = ["E402"]   # path no longer exists
"products/cds-text-sync/src/cds_text_sync/_cli_io.py" = ["E402"]   # now a 7-line shim
```

### D.3 Product test ownership is wrong, and the check can't detect it

`products/cds-text-sync/product.toml` claims **all 49 root unit tests**:

```toml
test_paths = ["tests/test_*.py", "../../tests/unit/test_*.py",
              "../../tests/regression/offline_regression.py"]
```

Mapping each root unit test to the code it actually exercises: ~14 belong to
`codesys-host` (`test_action_round_trip`, `test_bridge_import_order`,
`test_codesys_analyze_ui_launcher`, `test_daemon_name_resolution`, `test_discover_report`,
`test_find_child_transparent_locale`, `test_ide_sync_apply`, `test_online_session_guard`,
`test_project_file_path`, `test_project_snapshooter`, `test_snapshot_retention`, …),
3 to the analyzer, 1 to `visu_lint`, ~6 to `cds-cli`. Meanwhile
`codesys-host/deployment.toml` claims only 3.

`tools/ci_product_checks.py` cannot catch this:

```python
for pattern in _test_paths(name, manifest):
    matches = list((manifest.parent / pattern).parent.glob(Path(pattern).name))
    if not matches:
        raise SystemExit(f"{name}: test ownership pattern matches nothing: {pattern}")
```

It asserts only that each glob matches **at least one file**. It never checks that
ownership is exclusive, correct, or exhaustive. The check reads as a boundary guard but
is a non-empty-glob assertion.

**Target:** (a) re-partition `test_paths` per product; (b) strengthen the check to assert
every file under `tests/` is claimed by **exactly one** product — that turns the manifest
into a real boundary and makes future drift a CI failure rather than a silent lie.

### D.1 ~300 lines of unreachable visu render code

`visu/builder.py:1071 append_element`:

```python
golden_tmpl_name = catalog.get("golden_template")
if golden_tmpl_name:
    block, geometry = _render_golden_element(template, catalog, params, ...)
else:
    block, geometry = render_element(catalog, params, identifier, owning_guid, ...)
```

**All 9 element catalogs declare `golden_template`.** The only catalog without one is
`input_actions.json`, which `catalog.py` explicitly excludes via
`_NON_ELEMENT_CATALOGS = {"input_actions"}`. No test reaches the `else` branch.

Dead: `render_element` (63 lines), `_resolve_members` (99), `_render_color_member`,
`_render_scalar_member`, `_render_font_member`, `_render_font_color_struct`,
`_remove_color_uint_placeholder`, `_replace_color_struct_with_literal`,
`_unlink_font_color_from_style` — **≈300 lines**.

The data behind it is half-dead too. `catalog.py:75 _validate_catalog` requires
`base_members`, and 5 catalogs carry 24–30 entries (~2–2.6 KB each: button 2049 B/24,
label 2576 B/30, line 2195 B/26, rectangle 2487 B/29, textfield 2362 B/28) while the 4
newer ones (alarm-banner, combobox, image-switcher, lamp) carry `[]` — evidence the
schema already moved on. It is not *fully* dead: `_resolve_golden_geometry`
(`builder.py:606`) and `commands.py:1427 _default_for_param` still read it for geometry
defaults.

Tests pin the dead shape: `test_visu_builder.py:75-76` asserts
`len(rectangle_catalog["base_members"]) > 20`.

**Target:** delete `render_element` and its 8 helpers; make the `else` branch a raise.
Then narrow `base_members` to the geometry keys actually consumed, drop it from
`_validate_catalog`'s required list for catalogs that carry `[]`, and update the pinning
assertions. Sequence: delete code first (safe, proven unreachable), trim data second
(needs the geometry-consumer audit).

### D.4 Compat shims kept alive by their own tests

Twelve 7-line shims in `products/cds-text-sync/src/cds_text_sync/`: `_cli_io.py`,
`_cli_parser.py`, `_cli_handlers_{daemon,menu,project,vars,visu}.py`, `main.py`,
`visu_lint/{__init__,cli,dead_explicit_color}.py`. Canonical form:

```python
"""Compatibility wrapper for CLI I/O moved to :mod:`cds_cli`."""
import sys
from cds_cli import _cli_io as _impl
sys.modules[__name__] = _impl
```

Every remaining reference is a **test** importing through the legacy path
(`test_cli_text_output.py:25`, `test_cli_handlers_project.py:121`,
`test_cli_daemon_protocol.py:191`, `test_cli_handlers_daemon.py:22`,
`test_cli_handlers_visu.py:3/21/148/175`), plus `CLI.md:435/441`,
`codesys_analyze_ui_launcher.py:118`, and `tests/unit/analyze_helpers.py:36`.

`cds_text_sync.visu_lint` and `cds_text_sync._cli_handlers_menu` have **zero**
references — dead on arrival.

This is a self-perpetuating loop: the shims exist for backward compatibility, and the
only thing depending on them is the test suite that was never repointed. They will
survive indefinitely unless the tests move.

Related: the root `cds_text_sync/__init__.py` rewrites `__path__` and injects three
sibling product source roots into `sys.path` at import time — the mechanism that makes
the single compatibility wheel work. Keep it (it is the migration's public contract),
but it should be the *only* such mechanism once the shims are gone.

**Target:** repoint the ~9 test imports to canonical modules; delete all 12 shims; update
`CLI.md:435/441` and `codesys_analyze_ui_launcher.py:118`; drop the now-stale
`_cli_io.py` ruff exemption (D.2).

---

## Part E — Sequenced plan

Each wave is independently shippable and leaves the tree green. Waves 1–2 are the
prerequisites: they restore the guardrails that make the later, larger changes safe to
verify.

### Wave 1 — Restore the safety net *(S, do first)*

1. **D.2** — fix `compileall` targets; add `ide_bridge`; verify a broken file fails CI.
2. **D.2** — clean stale `per-file-ignores` in `pyproject.toml`.
3. **B.2** — unify blanking on the depth-tracking implementation; add a nested-pragma
   test. *This is a correctness fix, not a cleanup.*
4. **D.3** — re-partition `test_paths` across products; strengthen `ci_product_checks.py`
   to require exactly-one ownership.

**Exit criteria:** CI compiles the bridge; a syntax error in `ide_bridge` fails the job;
nested-pragma blanking is pinned by a test; every file under `tests/` is claimed by
exactly one product.

### Wave 2 — Clear the migration residue *(S–M)*

5. **D.4** — repoint test imports; delete 12 shims; update `CLI.md` and the launcher.
6. **D.1** — delete `render_element` + 8 helpers (~300 lines); `else` branch raises.
7. **C.3** — `engine/` to relative imports; drop the freed `sys.path` sites and `E402`
   exemptions.
8. **B.5** — key `_ELEMENT_PARSERS` on `(tag, data-cds-type)`; delete 6 promotion blocks.

**Exit criteria:** no module under `cds_text_sync/` is a `sys.modules` alias; no
unreachable branch in `builder.append_element`; `sys.path` mutation confined to
`ide_bridge/` and the root compatibility `__init__`.

### Wave 3 — Fix the layering *(M)*

9. **C.1** — `VisuCommandError` replaces 37 `sys.exit` calls; CLI layer translates.
10. **B.1** — one ST declaration parser; `variable_map.py` keeps only offset/XML concerns.
11. **B.3** — one command registry; `_DISPATCH`, `_cmd_help`, `build_parser` all derive
    from it; add a bridge-vs-CLI parity test.
12. **A.1** — `build_parser` → per-group `register()` modules (falls out of 11).

**Exit criteria:** `visu/commands.py` importable and usable without process exit; one
`parse_var_blocks`; adding a command is one edit + a passing parity test.

### Wave 4 — Break up the god objects *(L)*

13. **A.2** — split `project_snapshooter.py` into pure + UI; add CI tests for the pure half.
14. **A.3** — extract `ProjectionCodec` / `LayoutResolver` / `ManifestBookkeeper` from
    `FolderWriter` / `FolderReader` / `PatchBuilder`.
15. **A.5** — decompose `ProjectOptionsForm.__init__` into section builders + `load_from`.
16. **B.4** — one element-type descriptor table; collapse `preview._render_element` into
    `svg_export`.

**Exit criteria:** no class over ~300 lines outside UI modules; no function over ~80
lines; adding a visu element type touches one table plus one emit function per direction.

### Wave 5 — Test infrastructure *(M)*

17. **C.4** — convert 22 `_scenario_*` functions to pytest; retire the hand-rolled runner.
18. **C.2** — one logging catch per bridge command handler; delete inner swallows in the
    8 hotspot files; add the "no silent `except Exception`" lint rule.

**Exit criteria:** one test runner; `except Exception` count in `codesys-host` under
~150, none with an empty body.

---

## Part F — Non-goals and risks

**Non-goals.** Do not reverse the `products/` split. Do not convert `ide_bridge/` to
modern imports or packages — the IronPython constraint is real. Do not restructure the
`CTS00NN_*` rule layout (rule `.py` + `.md` pairs); it is repetitive by design and the
repetition is the interface. Do not touch the visu golden-template mechanism itself —
D.1 removes only the path it replaced.

**Risks.**

- *B.1/B.2 dependency direction.* Making the engine depend on the analyzer inverts the
  current layering. If that is unacceptable, extract a third shared module — but decide
  before Wave 1 step 3, because the blanking fix lands first and sets the precedent.
- *D.1 data trim.* `base_members` is not fully dead (`_resolve_golden_geometry`,
  `_default_for_param`). Delete the code in Wave 2; audit the geometry consumers before
  trimming the JSON.
- *C.2 scope.* Removing a swallow in `ide_bridge` can turn a silent no-op into an IDE
  crash. Restrict to handlers that already have a top-level catch, and land it last.
- *Wave 4 test churn.* `test_visu_builder.py` (2313 lines) and `test_folder_writer.py` /
  `test_folder_reader.py` pin current structure closely; budget test rewrite alongside
  each extraction, not after.

**Working-tree note.** `tools/ci_product_checks.py check_clean_tree` fails CI on any dirty
tree, and `refactor-spec.md` is not in `.gitignore` — this file needs to be committed (or
ignored) before the next CI run.

---

## Current implementation status

The following items are implemented and verified in the current worktree:

- A.1, A.5 — CLI parser registrations and `ProjectOptionsForm` section builders.
- B.1, B.2, B.3, B.5 — shared ST parser/blanking, command registry, and table-driven SVG import.
- C.1, C.4 — library-safe visu errors and pytest-owned offline regression scenarios.
- D.1, D.2, D.3, D.4 — dead renderer removal, bridge compilation, test ownership checks, and compatibility cleanup.
- Snapshot safety — snapshot import and compare-then-import are rejected while the IDE owns an active PLC/runtime session.
- A.3 (partial) — shared path safety and projection codec boundaries are now used by both folder orchestrators.

The remaining structural work is deliberately explicit:

- A.2 — completed: the 480-line WinForms implementation now lives in `project_snapshooter_ui.py`; `project_snapshooter.py` keeps a 7-line lazy adapter and remains backend-focused.
- A.3 — completed: manifest bookkeeping, projection codec, pending-file iteration, reader pipeline, and pending ST/XML discovery are extracted. `FolderWriter.write()` is a 48-line orchestrator; `FolderReader.read()` is a 3-line adapter to `_folder_reader_pipeline.py`, with discovery in `_pending_discovery.py`.
- A.4 — completed: `compose_skeleton` and `from_svg` now delegate to the isolated
  `_command_workflows.py` module; the public command module retains only the stable
  compatibility wrappers.
- B.4 — completed: XML-to-SVG export and preview both use table-driven renderer
  dispatch backed by the shared CODESYS/preview element vocabulary.
- C.2 — completed: notification fallback handling is centralized in
  `ide_run_action.py`, and the first sync-handler slice now logs failures from
  temporary-file cleanup, projection classification, document replacement, and
  dump inspection instead of silently discarding them. The build handler now
  logs project/application metadata, text extraction, active-application reads,
  and build-message cleanup failures. Capability probes and top-level command
  handling remain intentionally broad by design: the remaining broad catches
  are limited to CODESYS API capability probes, version-dependent property
  access, and best-effort compatibility fallbacks. `ide_handlers_build.py` now also logs
  failed temporary cleanup, application discovery, build-message decoding, and
  application-tree traversal instead of silently skipping them.
  `ide_handlers_project.py` now logs failures while reading project properties,
  selected-object GUIDs, and sync-folder metadata. `ide_handlers_crc.py` now
  logs PLC CRC directory inspection, CRC decoding, and temporary-file cleanup
  failures. `ide_handlers_cicd.py` now logs failures while resolving application
  metadata and test-plan targets instead of silently skipping them.
  `codesys_directory_operation.py` now logs failures in sync-folder metadata,
  host-name recording, application-count updates, and project-name/path reads.
  `ide_export_snapshot.py` now reports temporary-file cleanup failures through
  its existing optional logger.

The C.2 boundary is now explicit: command failures are caught and returned by
`ide_reverse_pipe_loop.handle_command`; inner broad catches are retained only
where CODESYS versions expose optional APIs/properties or where a fallback is
part of the compatibility contract. Operational cleanup and metadata paths were
converted to contextual logging in the touched handlers.

Latest verification: product manifests OK, analyzer selftest `127 blocks passed`,
isolated product wheels and root compatibility wheel OK, full source compilation
OK, and pytest `1221 passed, 4 skipped`.
