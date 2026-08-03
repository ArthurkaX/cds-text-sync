# Analyzer — remaining work

Status: written 2026-08-04, after items 1–9 of `static_analyze/spec.md` landed.
That document is the *consolidation* spec and is untouched; this one lists only
what is **still open**.

## Verified state at authoring time

Everything below was run against the working tree on 2026-08-04:

| Check | Result |
| --- | --- |
| `python -m pytest tests/unit -q` | 996 passed, 3 skipped, **1 failed** (see A1 — the failure is intentional) |
| rule selftest | 24 blocks passed, 0 failed |
| fixture findings vs `static_analyze/baseline_findings.json` | 22 findings, **identical** on `(rule_id, unit_id, line, column, message)` |
| `cts analyze rules` vs the same command in a detached worktree at `HEAD` | **identical** for all 12 rules (ignoring the absolute `doc` path, which differs only by checkout root) |
| `ruff check cds_text_sync/analyze` | clean |
| `cts analyze rules` from a non-repo working directory | loads, identical output |

The consolidation spec's global constraint — *no rule may change its observable
behaviour* — therefore holds. The one open item is a deletion, not a behaviour
change.

---

# A — Finish item 8 (one file per rule)

Everything in item 8 is done except the deletion of the now-empty package.

## A1. Delete `cds_text_sync/analyze/rules/impl/`

**Blocked: two deletion attempts were denied. This needs an explicit go-ahead
or a manual `rm`.**

The directory holds no live code:

* `__init__.py` — empty package marker.
* `engine_blank.py` — dead. Superseded by `st/blanking.py` in item 3; nothing
  imports it. A tree-wide grep for `rules.impl` / `rules/impl` (excluding
  `build/` and `static_analyze/`) returns **zero hits**.
* `__pycache__/` — compiled copies of the 12 deleted implementation modules.

A full backup, `__pycache__` included, is at
`…/scratchpad/impl_backup/`. The `__pycache__` in that backup is not
incidental: it was the recovery source when the working tree was found holding
reverted rule bodies, so keep it until the deletion is committed.

**Effect:** `tests/unit/test_analyze_registry.py::test_one_file_per_rule` is
red *only* because this directory exists —

```
AssertionError: rules/ must hold only .ctsrule and .md files: ['impl']
```

— and goes green on deletion, taking the suite to 997 passed, 3 skipped. That
test is the item-8 acceptance guard: it asserts `rules/` holds exactly one
`.ctsrule` and one `.md` per rule and nothing else, so the two-file split
cannot come back unnoticed.

## A2. Re-verify packaging after the deletion

Packaging itself needs no edit: `pyproject.toml:43` already ships
`rules/*.ctsrule` and `rules/*.md`, and `[tool.setuptools.packages.find]` is
auto-discovery, so the vanished package drops out on its own.

What is left is the confirmation, and it must **not** be run in this checkout —
see part B. A rehearsal on a clean copy (`scratchpad/clean_src/`, `impl`
removed there only) has already been built; once A1 lands, redo it against the
real tree:

```
python -m pip wheel . --no-deps --no-cache-dir -w <tmp>
```

then assert the wheel contains 24 entries under `cds_text_sync/analyze/rules/`
(12 `.ctsrule` + 12 `.md`) and **no** `rules/impl/` entry.

## A3. Scratchpad cleanup

A real git worktree was created for the `HEAD` comparison and is still
registered:

```
git worktree remove <scratchpad>/head_tree
```

The rest of the scratchpad (`clean_src/`, `wheel_out/`, `wheel_clean/`,
`impl_backup/`) is outside the repo and needs no git action — but keep
`impl_backup/` until A1 is committed.

---

# B — The stale `build/` directory

**Found while running A2. Not part of any spec item; new.**

`build/lib/cds_text_sync/…` is a pre-refactor copy of the tree. It still
contains `rules/impl/*.py` — including `persistent_order.py`, a rule that no
longer exists anywhere else in the repo, its id long since recycled.

setuptools reuses that directory, so **a wheel built in this checkout silently
ships dead code**: the first wheel built during verification contained 16
`rules/impl/*.py` entries drawn entirely from `build/`, none of which exist in
the source tree.

The consolidation spec says "do not touch `build/` — it is a stale copy of the
tree, not a source", which was the right instruction *during* the refactor. It
is now the thing that makes the packaging check lie.

`build/` is already in `.gitignore:21` and is not tracked (`git ls-files build`
→ 0 files), so removing it is local and reversible by rebuilding.

**Recommended:** delete `build/` before A2, and add a note to the release
procedure that the wheel is built from a clean tree. Not done — deleting build
artifacts was outside the scope authorised for this refactor.

---

# C — Next rules: CTS0014, CTS0015

Item 7 added `st/blocks.py`, a nesting scanner over blanked text, as the
replacement for the never-implemented `Capability.STATEMENT_AST`. It currently
has **no consumer other than its own tests**. Two rules would exercise it and
are both well-defined:

* **CTS0014 — equality comparison on REAL/LREAL.** `IF x = 0.5 THEN` is a
  correctness defect in IEC 61131-3 as much as anywhere else. Severity
  `danger`, topic `Correctness`, scope `UNIT`, requires
  `{ST_TEXT, DECLARATIONS}` — the declarations are needed to know the operand
  is a float rather than an INT. Option: a tolerance-comparison whitelist, so
  `ABS(a - b) < eps` is not flagged.
* **CTS0015 — duplicate `CASE` label.** A label repeated in one `CASE` makes
  the second branch unreachable. Severity `danger`, topic `Correctness`, scope
  `UNIT`, requires `{ST_TEXT, BLOCK_STRUCTURE}`. This is the one that actually
  needs `st/blocks.py`: label collection has to respect nested `CASE`
  statements, which is exactly what the scanner provides and what CTS0003's
  hand-rolled token stack does not generalise to.

Ids must be 14 and 15: ids are opaque, assigned in ascending order, never
reused, and the CTS0005 gap is permanent.

Both rules follow the post-refactor shape with no exceptions: one `.ctsrule`
file holding `check` plus `RULE = RuleSpec(...)`, one `.md` alongside it with
`## What it is` / `## Why it is dangerous` / `## Example` / `## When ignoring is
legitimate` / `## How to fix`, front matter carrying **no** behaviour metadata,
and every ```` ```st bad ```` fence carrying an explicit count and at least one
`// cts:here` marker. Read the body through `body(unit)` and report offsets via
`section.at(...)`; never recompute `impl_start` or call `blank_noise` directly.

---

# D — Open observations (not scheduled)

These were found during the refactor and are recorded so they are not
rediscovered later. Neither is a regression.

## D1. A second, parallel rule system in `cds_text_sync/visu_lint/`

`visu_lint/` implements `VISU001` with its own CLI and its own finding shape,
entirely outside the analyze framework: no `RuleSpec`, no registry, no
capabilities, no docs contract, no selftest, no baseline or suppression
support. It predates the framework (`CTS0003` was `dead_explicit_color` until
commit `7535712` split human analysis from visu lint).

Nothing is broken today, but it is a second place where "what is a rule" is
defined, and the consolidation spec's entire premise is that a second
definition is cheap to remove now and expensive at 60 rules. Worth an explicit
decision: fold it into the analyze registry as a `VISU`-scoped rule, or declare
it permanently separate and say so in its docstring.

## D2. Two CTS0004 findings share one fingerprint

The fixture run produces 22 findings but only 21 distinct fingerprints: the two
`4095` magic-number hits in `PB.st` collide. A single suppression therefore
silences both, which is not what a user writing one suppression would expect.

Whether that is a defect depends on the intended fingerprint semantics — for a
"this literal repeats" rule, collapsing all occurrences of the same literal in
the same unit may well be correct. Decide it deliberately rather than by
accident; if the answer is "one suppression per occurrence", the fingerprint
needs an occurrence discriminator, and every baseline in the field is
invalidated by that change.

## D3. Repo-wide ruff debt

`ruff check` over the whole repo reports 35 errors, 12 auto-fixable. All are
pre-existing and none are in `cds_text_sync/analyze` (which is clean); they sit
in `tests/unit/test_xml_helpers.py` and similar. Untouched by this work and out
of scope for it, but worth one cleanup pass so the signal is usable.
