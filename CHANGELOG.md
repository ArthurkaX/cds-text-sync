# Changelog

All notable changes to this project will be documented in this file.

---

### Unreleased

**`cts patch save` - hand your changes to a colleague.**

Packages the text you changed on disk so someone with the same project can copy
it in. It runs a compare against the open IDE, then copies only the
hand-authored text into a folder that mirrors the project structure:

```text
.dump/patch/patch_20260809-143512/
├─ project-view/
│  ├─ Application/PLC_PRG.st
│  └─ HMI/Visu/Main.xml
├─ patch.json
└─ README.txt
```

The receiver copies `project-view/` over their own sync folder root, replacing
files, then runs `cts compare` and `cts import`. No new command is needed on
that side.

What travels: changed `.st` and `.csv` projections, plus the XML of kinds listed
in `xml_in_view_kinds` (visualizations by default). What deliberately does not:
device descriptions, task configuration, the library manager and the `.dump/xml`
mirror - they encode the sending machine's state, and copying them across
machines is what makes untouched visu objects look modified.

Flags: `--out DIR`, `--sync-folder DIR`, `--zip`, `--dry-run`, `--bare`,
`--timeout`. Deleted objects cannot be shipped as files; they are listed in
`patch.json` and `README.txt` instead.

---

### Version 3.0.0 (2026-08-01)

**`cts analyze` - offline static analysis of the exported project-view.**

`cts analyze` reads only the exported `project-view/` tree: no daemon, no
`.dump/`, no IDE. It is the first piece of the analyzer planned in
`static_analyze/imp_plan.md`, delivered as vertical slices: the command
skeleton, the ST input model, the rule registry, and one rule per data
source.

**Optional desktop UI:** `pip install -e ".[ui]"` installs pywebview, then
`cts ui [--workspace <sync-folder>]` opens a local WebView2 window. The first
screen selects a workspace, runs the same offline engine as the CLI, filters
findings by severity/text, shows details, and opens the corresponding source
file. It is an optional dependency: ordinary CLI and CI installations remain
dependency-free.

`Project_analyze_ui.py` is installed with the other CODESYS menu stubs. It
starts that CPython UI for the active project's configured `cds-sync-folder`;
the ScriptEngine only launches the external process and does not host the UI.

**Commands:**

- `cts analyze --workspace <sync-folder> --format json|text|sarif` - run the
  analysis. Deterministic output sorted by path, position, rule id and
  fingerprint. The versioned JSON envelope (`schema_version`, `complete`,
  `findings`, `diagnostics`, `summary`) is stable from day one. A plain run
  writes nothing.
- `cts analyze rules` - list registered rules with severity, scope, kinds and
  required capabilities.
- `cts analyze explain CTS0001 [--format md]` - rule documentation with the
  mandatory "why it is dangerous" section.
- `cts analyze selftest` - runs every rule against the good/bad ST examples
  in its own documentation; a doc that rots fails the run.
- `cts analyze baseline create|update|check` - machine-written baseline of
  current findings (sorted, one entry per line for friendly diffs). `check`
  reports new findings and stale entries; a new finding is never accepted
  silently.
- `cts analyze triage --apply decisions.json` - scriptable triage: suppress
  (with a mandatory reason), fix-later, or baseline. State is written
  atomically.

An ST file can suppress a rule for its complete contents with a standalone
line such as `// cts:ignore-file CTS0001 -- legacy module` (or
the equivalent `(* ... *)` comment). Multiple rule IDs and `*` are supported;
the reason is mandatory.

**Exit codes:** `0` policy passed, `1` unsuppressed findings at or above
`--fail-on`, `2` configuration error or analysis cannot start, `3` incomplete
analysis with `--incomplete=error`.

**Rule model:**

A rule declares its data dependencies (`Capability`) and its granularity
(`Scope.UNIT` / `PROJECT` / `HISTORY`) instead of a numeric tier. An
unavailable capability becomes a `Diagnostic` and the run is marked
incomplete - analysis never crashes on one bad object, and a missing model
never looks like "all clean".

The release now ships 95 documented human-facing rules. They cover commented
out code, declarations, data flow, control flow, type and arithmetic hazards,
pointer/reference safety, strings, function blocks, project structure, and
several conservative style checks. The complete registry is listed in
`products/cds-static-analyzer/src/cds_static_analyzer/rules/implemented_rules.md`
and is available through `cts analyze rules`.

**Findings are identified by fingerprint**, not by file:line: schema
version + rule id + stable unit id + semantic anchor + normalised context.
Reindentation and line insertion do not change a fingerprint; the baseline
and suppressions survive reformats.

**Configuration (`cts-analyze.toml`, optional):** `fail_on` / `incomplete`
policy, git `base`, per-rule `enabled` and `severity` overrides, and
path-glob `[[rule_scope]]` exclusions. Suppressions live in
`.cts-analyze/suppressions.toml` next to `project-view/`, never inside it.

**Packaging:** rule files use the `.py` extension and are loaded explicitly by
`SourceFileLoader`. `.py` and `.md` ship in the wheel. CI runs `cts analyze
selftest` (no rule ships without executable docs), builds the wheel and asserts
the rule assets are in it, and enforces the asset budget: in-repo rule assets
are text/SVG only and stay well under 2 MB.

**Separate machine system:** `cts visu-lint --xml <generated.xml>` is the
JSON-only validator for the SVG-to-XML/LLM pipeline. Its `VISU001` rule is not
in the human analyzer registry, never appears in `cts ui`, and has no baseline
or triage semantics.

---

### Version 2.9.0 (2026-07-31)

**Read this before updating.** This release changes where the tool is installed and what the package is called. The installer migrates an existing installation for you, but it moves folders on your disk, so it is worth knowing what it will do.

**The CODESYS menu now lists 10 entries instead of 123:**

The CODESYS Script Engine scans its ScriptDir fully recursively and filters only by file extension — proven by probe: dot and underscore folders, nesting depth and the Windows hidden attribute hide nothing from it. The installer used to unpack the whole repository into ScriptDir, so every tracked `.py` in the project landed in **Tools > Scripting**, on every user's machine and not only on a dev box. The old backup path doubled it: `setup.ps1` wrote a second full tree to `ScriptDir\cds-text-sync.backup`, so anyone who had ever updated saw the list twice.

The install is now split in two. The tool itself — "the body" — lives outside ScriptDir, at `%LOCALAPPDATA%\cds-text-sync` by default or in any Git clone you point at. ScriptDir receives nothing but the generated `Project_*.py` stubs, each pinned to the body through a `CDS_HOME` literal.

- The stub folder and the file names are unchanged, so **toolbar buttons you set up earlier keep working**.
- Both layouts remain supported. An entry point declares its own body, so an existing in-ScriptDir install is untouched until you re-run the installer.
- `cts install-menu` regenerates the stubs; `cts where` reports which layout you are on.

**What the installer does to an existing install:**

- Finds your current installation in ScriptDir and **moves** it out to the new body location — never copy-then-delete, so a Git clone keeps its remote and its branch, and untracked files come along.
- If ScriptDir holds a developer symlink, only the link is removed; the target is left alone. (`Remove-Item -Recurse` follows a junction in Windows PowerShell 5.1 and would have deleted the target's contents.)
- Deletes the legacy `ScriptDir\cds-text-sync.backup` left by earlier versions, and writes future backups next to the body instead.
- **Fixes a long-standing data loss:** every previous update silently deleted untracked files under `profiles/` — a hand-written `profiles/astra.json` did not survive an upgrade. Those files are now stashed and restored.

**The package is renamed `cli` → `cds_text_sync`:**

The distribution was called `cds-text-sync` but installed a top-level package named `cli`. Any other project with a `cli` package — or a user with a `cli/` directory of their own — shadowed it silently, surfacing as an `ImportError` somewhere unrelated. For a tool people `pip install -e` next to their own code, that was a matter of time. `external_engine` becomes `engine` in the same pass.

**Upgrading needs `pip install -e .` once.** An editable install made before the rename still resolves the old name, and `cts` then dies with `No module named cli` — an error naming something you have never heard of. The installer detects exactly this condition and clears the stale install; if you upgrade by hand, run the reinstall yourself. The pipe name (`cds-cli-*`) is protocol, not package, and is deliberately unchanged.

**Reading a PLC variable no longer takes the daemon down:**

`cts read` built an online session when none was cached: `create_online_application`, then a walk over a list of login candidates calling `login()` on each. Every candidate has to fail before the call returns, and the single-threaded daemon loop serves nothing meanwhile — measured at ~145 s against a project with compile errors, after which the read failed anyway. Any command issued inside that window timed out, so the daemon looked dead rather than busy, and in practice needed a restart from the CODESYS menu.

Reads and writes now use the session they are given and refuse in about a second when there is none, which is what their docstrings already claimed. Opening a session stays with `cts connect` and `cts download`, where you asked for it and the wait is the point.

**`.dump/` no longer grows without bound:**

Every export wrote a timestamped snapshot and nothing ever removed one. `compare` and `import --dry-run` write one too, despite neither sounding like it touches the disk, so the folder grew by well over a megabyte per invocation — an afternoon of testing left 23 MB behind. Only the newest is ever read back, so ten are kept as a short manual undo trail, matching the existing `backup_retention_count` default.

**`--pretty` output is readable again:**

The text renderer collapsed a list to `[N items]` above five entries and printed every entry in full at five or fewer, which broke in both directions at once. `cts --pretty compare` returned five added objects carrying a ~300 KB XML blob each and printed all five whole: 1.5 MB across 16 lines. One more object in the project and the same payload would have rendered as `added: [6 items]`. Meanwhile `project-tree` showed nothing but `children: [8 items]`, and `read-log` nothing but `messages: [15 items]`.

Output is now rendered recursively with indentation, bounded by four limits on *size* — per scalar, per list, by depth, and by total lines. Whenever anything is left out the output says so and points at `--output json`, which stays complete and exact. The same compare payload renders in 9 KB. Flat output — `where`, `ping`, `permissions` — is byte-identical to before.

**Smaller fixes:**

- A bridge module that is present but fails to import is now reported as the defect it is, instead of being conflated with an absent optional module and degrading silently.
- `Project_compare` leaves the menu: it ran the same comparison as `Project_compare_ui`, which adds the object list and the import/export follow-up on top. `cts compare` still covers the no-dialog case, and `install-menu` removes the stale stub on its next run.
- Regression scripts and fixtures move under `tests/`. `offline_regression.py` was the largest file in the engine package and pip shipped all 1550 lines of it to users.
- Packaging metadata is consolidated into `pyproject.toml`, field for field.

---

### Version 2.8.3 (2026-07-27)

**Generated HMI screens now look designed (`cts visu from-svg`):**

A screen compiled from an SVG sketch was structurally correct and visually dated — cream field, cyan vessels, acid-green status bars, no type hierarchy, no grid. None of it was a bug: it was exactly what the defaults specified. Three causes, fixed together.

- **The extracted styles were overwriting a palette they had no opinion about.** `cli/visu/style_roles.py` curates a fallback per role and documents that `water`/`metal`/status roles have *no* CanonicalName anchor — they are ours, not CODESYS's. But `cli/visu/themes/*.json`, snapshotted from installed styles, redefined them from arbitrary entries and won the merge, so `--theme flat-style` (the default) yielded `water #00F3FF` and `success #ADE204`. `load_theme` now strips the roles we curate and re-fills them from `style_roles`; everything CODESYS genuinely defines — fonts, native control colours, frame, border, accent — still resolves through the project's style. Dropping `--theme` used to give a better screen than keeping it; that inversion is gone.
- **`var(--water-dim)` never resolved.** `resolve_color` maps it to the dotted key `water.dim`, the JSON themes store `water-dim`, so a `.pipe-water` shape took its fill from the theme and its stroke from the built-in fallback — a mismatched pair by construction. Hyphenated roles are now aliased to dotted at load time.
- **`--text-bright` was missing from all twelve presets.** `.inverse` worked anyway because `svg_import.parse_svg` layers the curated palette *underneath* the theme — but `builder` resolves straight out of a theme dict for `cts visu add`, with nothing underneath, where the same hole is a `ThemeError`. `_finalize` now makes every theme self-sufficient for every role `style_roles` knows, and a new test walks every `var(--role)` in `stylesheet.css` against every theme so the next hole fails in CI rather than at a user's prompt.

**`cts visu preview` — see the screen before it reaches the IDE (new):**

- A sketch is deliberately colourless (`class="pipe-water"`, never a hex), so opening it in a viewer showed black shapes on white. Nobody — human reviewer or authoring model — could see the result before importing it. `cts visu preview --svg FILE` renders `<file>.preview.svg` + `.preview.png` with the colours the compiler will actually emit.
- The preview renders from the **parsed element list** and asks `builder._resolve_golden_colors` for the colours, so preview and compile cannot disagree about geometry, colour, or the baseline→top-left conversion: one resolution path, used twice. Native controls are drawn the way the style paints them rather than left invisible.
- Rasterisation uses a headless Chrome/Edge when one is installed (`$CHROME_PATH` overrides the search); without a browser the SVG is still written. `from-svg` writes a preview on the way through unless `--no-preview`.

**`cts visu lint` — a design contract a weak model can follow (new):**

- `cts visu check` validates a *compiled* screen — bounds, member consistency, Text-ID invariants, the things CODESYS would reject. That is correctness, and it runs too late to help someone still drawing. `cts visu lint --svg FILE` checks the sketch for what makes a valid screen look unfinished: off-grid coordinates, text wider than its box, a font size outside the scale, a button too small to press, a field with nothing bound to it, a captionless button, overlap, near-miss gaps.
- `--fix` snaps the mechanical findings by splicing the affected start-tags back at their own character offsets, so comments and formatting survive byte-for-byte. `from-svg` runs lint and prints findings; only `--strict` makes them fatal.
- Two rules had to know what they were grading. A `<text>` `y` is a *baseline* — including a textfield's — so the rule grades the **compiled box top** and shifts the baseline by the same delta; snapping the baseline itself would push the box off-grid, the opposite of the intent. And `rx` on a `<rect>` is a corner radius, not a position, so it is exempt: `--fix` would otherwise have rounded a deliberate 2px radius down to a square corner. On an `<ellipse>` the same attribute is real geometry and stays graded.

**What ten authoring runs found (`cts visu lint`, `--fix`):**

Ten weak-model agents were given only `skills/cds-visu-svg/SKILL.md` and asked to draw a screen each. Most of what came back was not a modelling failure — it was the tooling teaching the wrong lesson.

- **`--fix` could rewrite the wrong element.** `index_source_tags` masked `<defs>` but not comments, so a comment that merely *named* a tag added a phantom entry to the source index — and from there every finding was attributed to its neighbour. The shipped `pid-schematic.svg` says "a pipe is a thin RECT, not a `<line>`" and silently mis-indexed the twelve elements after it. Depending on where the drift landed, a fix was either applied to an innocent element or dropped on the floor. Comments are now masked the same way `<defs>` is, and two tests pin it.
- **The text-width estimate was one constant doing four jobs.** 0.65 em/char is about right for uppercase and overstates mixed-case prose by a quarter, and that estimate is load-bearing in the default box width of an unsized `<text>` plus the overflow, overlap and crowding rules. Inflated boxes reported collisions that were not there, and three of the ten authors dismantled a working layout to silence them — one deleted every annotation on a P&ID. Widths now sum per-character advances.
- **The linter's gradient pointed at an empty screen.** Every rule rewarded removing content and none noticed a blank one, so an untouched starter screen scored a clean `[OK]` — and one author shipped exactly that. Two rules push back: `empty-panel` (a panel with nothing in it) and `scaffold` (the starter placeholders are still here). `scaffold` is *info*, not a warning: the first thing an author sees should not be a complaint about code they did not write.
- **Crowding fired on P&ID drawings.** A 4px gap is a slip between two cards and correct between a pipe and the vessel it enters, so pairs of `.pipe-water`/`.metal` shapes are exempt.
- **Findings could not be located.** "label #16 overlaps rectangle #27" is only resolvable by counting tags by hand; findings now quote the element's text and the coordinates as written, so a `<text>` reports its baseline rather than a derived box top. They also name the shape that gets drawn rather than the parser's category for it — `parse_svg` files every plain shape under `rectangle` and keeps the real one in `params["shape"]`, so a circle used to be reported as a rectangle the author never wrote.
- **`--fix` needed more than one pass.** The font-scale rule rewrites `font-size`, and a baseline is graded through the box top — which is the baseline minus that font size. It now iterates to a fixed point (bounded at five) and says so if two rules ever disagree.
- New rules for the traps that were silent: `control-tag` (a `<circle data-cds-type="lamp">` is the obvious shape for an indicator light and is just an ellipse — `data-var` is dropped and it sits at one colour forever), `inert-class` (`class` on a button, textfield or lamp changes nothing at all — not size, not colour), `text-anchor` (an anchor with no `data-width` aligns against a guessed box).
- `--fix` no longer resizes a `<circle>`: `r` is graded on its diameter, so `r="6"` — a 12px dot already on the grid — is left alone instead of being inflated to 16px.
- Malformed XML now surfaces as advice rather than an `ElementTree` traceback, quoting the offending line and, for the commonest cause, explaining that `--` cannot appear inside an XML comment.
- **A text box hangs below its baseline, and nothing said so.** SKILL.md documented the box *top* (`y − font-size`) and never the height, which is `max(16, font-size × 1.4)` — so the bottom edge sits `0.4 × font-size` under the baseline, 11px for a `.value`. An author sizing a KPI card to the baseline of the number inside it overflows it by three pixels and cannot see why; one screen did this three times over. The five per-class numbers are now in SKILL.md and pinned by a test, so the doc cannot drift from `_estimate_text_height`.
- `cts visu new` warns when the canvas is below 480×320 (the size the layout blocks are dimensioned against — under it they collide) or has a side that is not a multiple of 4 (the halves it computes then land off the grid the linter enforces).
- One limitation the runs made obvious enough to write down: **a screen authored here is read-and-press.** Only buttons and plain shapes carry input actions — `element_textfield.xml.tmpl` emits an empty `VisualElementInputActions` — so a textfield displays `data-text-var` and cannot be typed into. An operator can start, stop, toggle and navigate, but cannot key in a setpoint except through a button that writes one. SKILL.md now says so under "Unsupported", including that a writable field added in the CODESYS editor does not survive a round trip: `to-svg` reads a textfield's geometry, variable and font, not its input action.

**Type scale, layout skeleton, and the authoring skill:**

- `stylesheet.css` gains a five-step type scale as classes — `.h1` 22, `.h2` 16, `.value` 28, `.label` 12, `.caption` 11 (`.title` stays as an alias of `.h1`) — plus `.card`, `.muted` and `.inverse`. An author picks a class; a bare `font-size` is now a lint finding.
- `cts visu new` no longer copies a fixed seed file with four floating examples whose coordinates ignored `--w/--h`. The skeleton is composed from layout tokens, so the canvas size drives the layout, and blocks that will not fit are dropped rather than squeezed — narrow canvases fall back to one KPI card, short ones drop the lamp rows. Verified lint-clean at 800×480, 1024×600, 1280×800, 640×400 and 480×320. That is the tested envelope, not a guarantee for every number: 480×320 is the floor the blocks are sized against and below it they collide, and a canvas whose sides are not multiples of 4 puts the halves it computes off the grid the linter enforces. `visu new` now warns in both cases rather than handing back a skeleton that fails its own lint.
- `skills/cds-visu-svg/SKILL.md` gains a "Layout rules" section (4px grid, 24px page margin, bands, type scale, touch targets, the baseline rule) and a "look at what you made" step — render the preview and read the PNG before asking for approval. Both shipped examples were rewritten and now lint clean; a test asserts they stay that way, because SKILL.md tells an authoring model to copy from them. The stale claim that inline `<style>`/`:root` is unsupported is gone — `_parse_inline_theme` has supported it all along.
- A pipe is now drawn as a thin `<rect>`, not a `<line>`: a CODESYS line has no width member, so `<line>` always draws one pixel wide. Fine for a `.divider`, invisible for a process line.

`--` is illegal inside an XML comment, which made naming a flag in the skeleton's own guidance block (`cts visu lint --fix`) render the whole file unparseable — as a `ParseError` on line 5, saying nothing about comments. Guarded by a test.

**What five end-to-end runs against a live project found (`--gvl` binding):**

The ten earlier runs stopped at `lint`; these five compiled into a real FACTORY I/O project and bound to its actual `FIO_SIGNALS` / `GVL_Sensors` / `GVL_Routing` globals. Every one of them produced a broken GVL, in two different ways that turned out to share a cause.

- **A variable path names its owner in the first segment, and the lookup read the last.** `ensure_gvl` matched `rpartition(".")`, so `GVL_Sensors.Scale.Q` was searched for under a GVL called `GVL_Sensors.Scale`, found nothing, and fell through to declaring the leaf. Nine sensor lamps therefore emitted nine `Q : BOOL;` lines into one `VAR_GLOBAL` — ST that CODESYS refuses to compile. The owner is the *first* segment; what `GVL_Sensors` declares is the instance `Scale`.
- **Every hardware-mapped global was invisible to the dedup.** Fixing the lookup exposed the larger defect underneath: the declaration regex `^\s+(\w+)\s*:` requires the colon to follow the name, but real PLC globals are written `Emitter AT %QX0.3 : BOOL;`. Nothing located at an `%I`/`%Q` address had ever been seen by `scan_project_gvls`, so a screen bound to `FIO_SIGNALS.Emitter` re-declared `Emitter` in its own GVL — a silent shadow of an I/O point, which is worse than the crash because it imports cleanly. Both scan sites now share one `_DECL_RE` that accepts the location.
- **A declaration only counts where the reference looks for it.** The screen binds the full path it was written with, so `Q : BOOL;` in `VisuVars` produces `VisuVars.Q` and `GVL_Sensors.Scale.Q` still resolves nowhere. `--gvl` now declines instead of inventing: unresolvable references are reported as `[WARN] Not declared: <path> — <why>`, and two paths can no longer collapse onto one identifier. Against the live project all five screens now compile to `All runtime variables already declared; GVL not modified`, which is the correct answer when an author binds to globals the PLC program already owns.

**What those runs found in the skill document:**

- **`--sync-folder` was undocumented and all five authors needed it.** Each guessed it from context; a reader following the document literally would have pointed every command at the wrong directory. It is now stated once, up front, as applying to `lint`, `preview` and `from-svg` alike.
- **The baseline rule was being applied to anchored text, where it does not hold.** Two authors independently computed the scaffold's own caption as off-grid (`40 − 11 = 29`) and concluded the shipped starter was broken. It is not: anchored text centres on `y` using the *box height*, so the top is `40 − 16/2 = 32`. The document had said only "centred on `y`" and never gave the formula. `text-anchor="end"` gained a worked example too, after an author wrote the box's right edge as `x` and pushed it off-canvas.
- **"You never write a colour" contradicted the lamp table three sections later.** `data-color` names a role, not a hex, but the absolute phrasing made it read as a rule being broken. Softened to what was always meant.
- **The preview draws a lamp as a circle after telling you to draw a square.** That is the preview being honest about the native round bitmap, but two authors read it as their sketch having been rewritten. Stated, along with why textfields show `%3.1f` rather than a value.
- **A normally-closed E-stop has no representation.** TRUE means healthy, and a green lamp bound straight to it is correct while reading backwards to an operator. There is no sketch-side inversion; the guidance is now to carry the polarity in the label or bind an inverted flag, and never to let colour alone imply it.

**What those runs found in the linter and the preview:**

The same five screens were the first drawn end-to-end by someone other than their author. Most of what the linter said about them was wrong — not wrong about geometry, wrong about whose geometry it was reading.

- **Crowding was measuring its own estimate.** A `<rect>` carries its width in the file, so the gap beside it is a number somebody chose; a `<text>` carries a baseline and a font, and its box comes from `_estimate_text_height` plus a table of glyph advances. SKILL.md sets a label's baseline 24px above its field's, which for a 12px label over a 16px value leaves exactly 4px between the two derived boxes — so following the documented rhythm produced the finding, and the only way to clear it was to stop following it. Text-against-text is now exempt the way P&ID pairs are. Type that really collides is still an `overlap`, type off the rhythm is still a `grid` finding, and page furniture — two cards, a card and its caption — keeps the rule, because there the gap really is a slip.
- **An unsized textfield defaulted to 100×100.** A box nobody asked for: it overflowed whatever card held the field, which the linter then reported as an overlap the author had not drawn — and the compiled control really was 100px tall in the IDE. A field with no `data-width`/`data-height` now falls back to the same estimate a plain `<text>` gets, which is the one the document promises. Falling back at all is still worth a warning, and `unsized-field` is that warning: a label's width can be estimated from its own text because that text is what appears, but a field's content is `%d` in the file and `1247` on the screen, so the estimate sizes the box to the format string and the value runs out of it. It is the one geometry a field cannot infer.
- **"The card overlaps the label" sent authors looking for the wrong mistake.** When a child's box starts inside a container and ends past its edge, the author sized the parent and let the child grow — a different defect from two labels that drifted into each other, and it is the child that is wrong. Split into `overflow` (filed against the child) and `overlap`. The distinction is drawn on type rather than on which box is bigger, because a 100px field inside a 72px card has the *larger* area and is still the thing that overflowed.
- **A captioned button that does nothing is worse than a blank one**, because the operator has no way to tell — `inert-button` is a warning now, not info. Both button findings also quote the caption and the coordinates: five buttons on one screen made `button #32` a tag-counting exercise. The index is no longer duplicated into the message, which the reporter already prints.
- **The preview drew every label 2px right of where it was written.** The 2px inset is real — it is the gap a native control keeps between its frame and its value — but it was charged to plain labels too, which CODESYS draws flush. So a label written `x="48"` came back at 50, and lining it up against a card edge always looked 2px wrong in the one view an author reads to check alignment. The inset now applies to textfields only.
- **A `card` on the screen background is invisible, and the report for it was "panel and card are the same colour".** They are not — `#FFFFFF` against `#EDEFF2`, verified through the theme palette, the compiled `params["fill"]`, and the rendered preview — but a card *is* one step in from the panel that holds it, which in the light palette lands it within 3% of the screen background. Drawn straight onto the background it renders as nothing, and two of the five screens did that eight times over. New `lonely-card` rule, gated on the resolved palette rather than on an assumption, so the dark scheme — where the two are visibly apart — never sees it. SKILL.md now says what `card` is for.
- **The `visu` flag help described a scope the handlers do not have.** `--out` was documented "(for from-svg, to-svg)" and is read by `new` and `preview` as well; `--width`/`--height` said "(for create-screen)" and drive `visu new`; `--svg` said "(for from-svg)" and is required by `preview` and `lint`; `--theme` named only `from-svg`; `--w`/`--h` had no scope at all while serving two subcommands with different meanings. Corrected against what each handler actually reads.
- **Two screens compiling at once could share one Text ID.** Every caption in a project draws from one `GlobalTextList.xml`, and an id was handed out by reading the current maximum and appending — with nothing between the read and the write. Two `cts` runs against one project (two authors, or one author with two screens in flight) both read the same maximum and both append it, and the result is two screens whose labels point at one entry: in the IDE, a caption from the wrong screen, and no check we have can see it, because the XML is well formed and every reference resolves. Allocation now takes a lock file beside the list. A lock older than 30s is treated as a process that died mid-write and broken rather than waited out — one crashed run must not wedge every later compile behind a file nobody has heard of.
- **Every generated screen claimed the same object identity, and importing the second one froze the daemon.** `builder.build_screen` fell back to a shared constant — `11111111-1111-1111-1111-111111111111` — for the visualization's own guid whenever the caller did not supply one, and neither call site ever did. That guid is not a local placeholder: it is written into the project verbatim, and a snapshot exported by CODESYS itself after the first import shows the screen sitting in the project under it. So the first screen imports fine and every screen after it arrives claiming to *be* that screen. CODESYS raises an overwrite prompt, and because the script engine is single-threaded a modal dialog stops the whole daemon rather than the one call that opened it — `import` hung past its 180s timeout, and the `ping` and `read-log` sent to diagnose it hung too, which reads as a dead process rather than a question waiting for an answer. Screens now get a fresh guid each; an explicit `visu_guid` is still honoured.
- **`--gvl` said "Updated GVL" when it had updated nothing.** `ensure_gvl` returned the same path whether it appended declarations or found every reference already declared, so the caller could not tell the two apart and always reported the write. On a project with real signals that is the *normal* case — a screen bound entirely to existing GVLs — and the author is told their GVL just changed, goes to look, and finds either nothing or leftovers from an earlier run they now have to explain. `ensure_gvl_result` reports `(path, written)`; `ensure_gvl` keeps its old contract for existing callers.
- **`from-svg` with no `--screen` reported a missing file instead of a missing argument.** An empty name resolved to `<project-view>/.xml` and came back as `Screen file not found: ...\.xml` — which reads as damage to the project, and names a file the author never asked for. It now says which flag to pass.
- **Nothing measured the padding the skill grades screens on (`padding`, new rule).** "24px page margin, 16px panel padding" is written into the layout rules and followed by the claim that lint grades against them — and only the page margin was ever checked. Four of five screens drawn against the skill came back "Sketch OK: no design problems found" with content sitting exactly on the edge of the box holding it: a row of lamps on the panel border, a value field ending on its card's bottom edge. It is not an overlap — the child is properly inside its parent, which is why every other rule waves it through — and it renders as content clipped by its own container. The rule measures content only: a rectangle flush inside a card is the accent bar `cts visu new` draws itself, and a line across a panel is a divider. The bar is 8px, half the documented padding, so a deliberately tight layout is left alone and only flush-or-nearly is reported, and it names the *innermost* container — a card sharing its panel's bottom edge is one problem, not two.
- **Recompiling a screen added a second copy of it instead of replacing it.** `--screen <Name>` is the documented way to compile a sketch into a screen that already exists, and `from-svg` appended to whatever was there: the second run turned 31 elements into 62, each new one landing exactly on top of its twin. Nothing in the tool showed it — the sketch was still 31 elements, the preview rendered from the sketch, and `[OK] Compiled 31 element(s)` is what a correct run says too — so it surfaced only as `check` reporting overlaps for elements the author had never drawn twice, and in CODESYS as a screen with every label stacked. It also meant an element deleted from the sketch could not be deleted from the screen, since only additions ever reached it. `from-svg` now clears the element list first and says how many it replaced; the identifier counters keep running forward so no fresh element reuses a name CODESYS has already seen. Creating a screen (`--create-screen`) is unaffected.
- **`visu check --name X` answered "--screen is required".** `--name` belongs to screen *creation* (`new`, `create-screen`); the subcommands that work on an existing screen — `add`, `list`, `check`, `to-svg` — take `--screen` and ignore `--name` entirely. Three of five authors reached for `--name` first, and the reply left them looking at a screen name they had just typed beside a message saying they had given none. When `--name` is present the error now names the flag that carries it: `pass --screen T_Sensors (--name is for creating one)`. `check` was also missing from the skill's workflow, which is why it was being guessed at from `--help`.
- **Only five named entities are legal in a sketch, and the skill never said so.** `&rarr;` and `&le;` are the obvious way to write an arrow or a threshold in a caption, they are valid HTML, and they fail the parse with *undefined entity* — taking the whole file with them, so the error arrives as "your sketch is malformed" rather than "this one character is not XML". Documented, with the three ways to write it that do work.
- **A caption can state a live value it is not bound to, and nothing said so (`static-state`, new rule).** Text without `data-text-var` compiles to a Text ID: fixed at import, identical for the life of the screen. Three screens in a row shipped one anyway — a red `E-Stop = Stopped` button, a header reading `9 sensors — diagnostics active` — because the phrasing is natural and every geometric rule passes it. The result is the most confident-looking thing on the screen reporting a state it has no connection to, which on an HMI is worse than an ugly layout: it says *Stopped* while the machine runs. The rule reads what is to the right of `=`, `:` or a spaced dash and reports it when it names a state. It deliberately does not match a state word on its own — `Running` beside a lamp is the legend that screen needs, and `Motor Running` is that legend with the machine named; firing on those would penalise every screen labelled correctly. Bound fields are exempt, since there the text is a format string. Documented in the skill with the fix.

**Dark screens (`--scheme dark`, new):**

A night shift reads the same HMI in a dark control room; for an industrial screen that is not cosmetic. The sketch format already made most of it free — an author writes `class="panel"`, never a hex — so no example sketch, no `stylesheet.css` rule and no `themes/*.json` needed to change. What had to move is the ownership boundary.

- **In dark the curated palette is authoritative, not a fallback.** Every CODESYS visual style that ships is a light style, so sampling one for `text` while painting the panel behind it dark is precisely how white-on-white happens. `style_roles.curated_roles(scheme)` widens from 15 roles in light to all 41 the dark palette names — surfaces, the text on them, frames, native control colours — and `themes.load_theme(name, scheme)` strips and re-fills those, so two different `--theme` values compile the same dark screen. Light is untouched: it still defers to the project style for everything CODESYS genuinely owns.
- **Buttons and textfields were unreachable by any palette.** `builder._resolve_golden_colors` forces their fill and frame to `None` so the style owns them at runtime — correct for light, and a light island on a dark screen. The gate now applies only where the role is *not* curated in the active scheme. `textfield.json` had no `themeable_colors` block at all and gained one for the two members its template already carried; `button.json`'s fill role moved from `primary` to a new `button.fill`, so a dark button is a dark surface instead of a shouting accent blue.
- **A style-linked colour cannot be overridden in place.** A colour member written as a struct with a `CanonicalName` resolves from the project style and the literal beside it is ignored — and blanking the name crashes the CODESYS build. The short-form `<Single Name="Value" Type="uint">` is the only encoding that wins, and it *replaces* the struct rather than sitting beside it, so a member id still appears exactly once. Light continues to emit the struct, byte-for-byte what it emitted before.
- **Font colour is written in three places and drawn from one.** A label carries it as a plain member, as a style-linked struct beside it, and inside the font descriptor — which holds it twice more, as an `ExplicitColor` literal and a `NamedColor` link to the style's `Font-Default-Color`. All three already carried the right value, and the first dark screen still came back with every label in the style's black, unreadable on its own panel: while that link exists the literal is ignored. Which of the three mattered was settled by importing a probe screen carrying four encodings of the same label into a live IDE — only nulling the link changed what was drawn, and switching the colour member to the short form changed nothing at all. Dark now emits `<Null Name="NamedColor" />`, the encoding CODESYS itself uses for a screen background and for the stock combobox font, and rewrites `ExplicitColor` alongside it because the button template hard-codes a black one. Light keeps the link and keeps following the project's style. The comment in `builder._render_font_color_struct` asserted the opposite and had been wrong from the start — light could not have exposed it, since a curated light `text` and the style's black look alike.
- **Two new roles, so a pairing is named rather than implied.** `field.text` (a textfield's value colour) and `button.fill` have to be chosen together with the box behind them. In light both derive from the role they refine (`text`, `primary`) — a style snapshot predates them and never names them, so left to a literal fallback they would have silently ignored the project style.
- **The sketch carries its own scheme.** `cts visu new --scheme dark` records `data-cds-scheme="dark"` on the root `<svg>`; lint, preview and `from-svg` read it, so the rest of the workflow needs no flag and preview cannot drift from compile. `--scheme light|dark` overrides it for a single run. The scheme is resolved by a pre-parse (`svg_import.read_scheme`) before the theme is loaded — loading a light theme first would layer it over the dark base palette and repaint the screen light again, but only when `--theme` was supplied.
- **The scheme survives a round trip.** A compiled screen does not record which scheme produced it — the two differ only in the colours they resolved to — so `cts visu to-svg` handed back a sketch with no attribute, and recompiling it repainted a dark screen light. Decompiling now infers the scheme from the screen background, whose two curated values (`#F4F5F7` and `#10141A`) are separated by most of the luminance range, and stamps `data-cds-scheme="dark"` when it is dark. Light stays unstamped, matching what `cts visu new` writes. The inline `:root` block follows the same answer, so a dark sketch no longer carries light variables under a dark stamp. `--scheme` now also reaches `to-svg` for the case the guess is wrong — a hand-set dark background on an otherwise light screen.
- **Preview follows.** `_resolved_colors` hands the scheme to the compiler instead of arriving at the same colour by a different route, its light-biased fallbacks (`#DDDDDD`, `#808080`, `#000000`) now come from the palette, and the `--grid` hairline flips to white on dark — a black one at 6% opacity reads as "the flag is broken".
- **Lamps are deliberately excluded.** Their colour comes from `Element-Lamp-*` and stays identical in both schemes: an indicator that changed meaning with the colour scheme would be a safety problem.

Light output was verified byte-identical, not merely tested: the same fixture screen compiled against `flat-style`, `basic-style` and `white-style` produces the same 508630 characters before and after. New tests pin the contrast of every text role against the surface it actually sits on in *both* schemes — the rule that would have caught white-on-white before it reached the IDE — plus scheme precedence, the struct/short-form switch, and that no preset can drag a light `text` into a dark screen.

**The sketch commands no longer pretend to need an IDE:**

`cts visu lint` and `cts visu preview` grade a file. They consult the daemon only to pick up an optional project-level `visu.css` — and `_optional_project_view` was written to shrug that off — but the failure still cost the full 10s project-command timeout and printed `[ERROR] Could not get sync folder from daemon … Make sure the reverse-pipe daemon is running inside CODESYS` before succeeding. These are the first two commands a new user runs, usually before CODESYS is open, so the one flow that is meant to work offline was the one that looked broken. `_resolve_project_view` gained `timeout` and `quiet`; the optional path waits 2s — ten attempts at the default 200ms daemon poll — and says nothing. The project commands are unchanged and still explain themselves.

**`cts visu to-svg` gave back a sketch that was not the screen:**

Decompiling is how an existing screen enters the SVG workflow, and how a compiled one is reviewed. Three things it dropped only became visible by linting the round trip — the original sketch lints clean, so nothing upstream could have caught them, and each of the three does damage twice: the sketch is wrong, and recompiling that sketch writes the loss back into the screen.

- **Every caption came back moved.** A CODESYS text element is a box plus an alignment; an SVG `<text>` is a baseline plus an anchor, and `_parse_text` converts the one into the other on import. The export emitted the raw box top as `y` and never read the alignment members at all, so a centred caption came out flush left and every line of text rose by one font size. It now inverts the import: `HCENTER` restores `text-anchor="middle"` and `y + height/2`, `RIGHT` restores `text-anchor="end"`, and left-aligned text gets `y + font-size` — the same fallback size the builder uses when a label carries none.
- **Buttons came back inert.** A button's behaviour is split across two places in the compiled XML — tap and toggle in `ConfiguredComplexInputs`, per-event actions in `VisualElementInputActions` — and the export read neither, so a decompiled screen had six buttons that looked right and did nothing. `_read_input_actions` recovers all of it as `data-cds-action` clauses (`TAP`, `TOGGLE`, `OnMouseClick: ST|toggle|screen`), suppressing the event half when the dialog reader has already claimed it so a dialog button does not emit its snippet twice. A fixed-point test now compiles, decompiles and recompiles, and asserts the wiring is identical.
- **Estimated text boxes failed the project's own grid rule.** `_estimate_text_width/height` are what a `<text>` gets when the author wrote no `data-width`/`data-height`, and they landed on arbitrary pixels — so `lint` reported sixteen grid findings against numbers no one had written. Both now round **up** to the 4px grid, which keeps the box at least as wide as the glyphs need. The alternative — omitting the estimates on export — was rejected: it would silently move genuinely off-grid boxes in hand-authored CODESYS screens. The documented below-baseline overhang shifts with them (4/5/8/10/12 px for `.label`/`.caption`/`.h2`/`.h1`/`.value`); SKILL.md and its test move together.

A compile → decompile → lint cycle on the reference project's 95-element screen is now clean in both schemes.

**`from-svg --create-screen --replace` (new):**

Recompiling a generated screen meant deleting its `.xml` first, and a fresh compile mints a fresh object Guid. That Guid is the screen's identity on `cts import`, so the delete-and-rebuild loop adds a second screen in CODESYS beside the first rather than updating it. `--replace` rebuilds in place and keeps the Guid. Without it an existing screen is still never overwritten, and the refusal now names the flag instead of leaving `rm` as the only way forward.

Unit suite: 769 passed, 3 skipped (was 521/3).

---

**ACTION round-trip (`cts export` → edit → `cts import`):**

- ACTIONs (and other declaration-less POU children) expose an `Implementation` section only, so `st_projection_content` never matched its two-section branch and exported them as a bare body — no `ACTION <name>` header, no `// --- implementation ---` marker. The file was not self-describing: `_detect_st_kind` could not classify it, and the import path could not tell the body apart from a GVL/DUT declaration, so it routed the text into `textual_declaration` (absent on an ACTION) and the edit never reached the IDE. The object landed in `skipped_projection_objects` while `cts compare` kept showing the diff.
- The header is now synthesised on export from the entry's own `MetaObject/Name`, and stripped again by `split_st_projection_values` on the way back, so the text-first path (`folder_reader`) and the patch builder store the bare body in the `Implementation` blob exactly as before. Both directions are covered by `tests/unit/test_action_round_trip.py` — a forward-only fix would write the header and the marker straight into the stored ST code.
- Splitting of projected `.st` text now lives in one place, `src/ide_bridge/ide_st_text.py`, shared by the update path, the creation path and `update-pou`; the three used to disagree about what a marker-less file means. A marker-less file is still a **declaration** — that is what GVLs, DUTs and empty-bodied POUs project to, and treating it as an implementation would silently write their declaration nowhere.
- `.st` files exported before this change (bare body, no header) keep working without a re-export: when the target object exposes no declaration but does expose an implementation, the body is routed to the implementation. Objects that do have a declaration are never re-routed.
- An empty or whitespace-only `.st` is no longer reported in `updated_text_objects`: nothing is written, so claiming an IDE update was misleading.
- The skip reason for non-ST projections (`.csv` textlists, alarm tables) no longer advises `update-pou`, which only understands `.st`.

Problem surface identified from eddiedon's report in #63; implementation and reverse-direction fix are independent. Verified live against a 894-object project in both `text_first` and `xml_first` sync modes: declaration-only objects (GVL/DUT/interfaces — 303 of them) still route to `Interface`, POUs and methods to both sections, and `cts compare` stays clean across an edit → import → revert cycle.

---

### Version 2.8.1 (2026-07-25)

**Non-English UI locale fix (import resolution + on-disk tree):**

- On a non-English CODESYS UI locale (e.g. Chinese zh-CN) the native XML snapshot encodes the `Path` array of standard objects using localized labels (`PLC逻辑`, `任务配置`) while each object's own `Name` field stays English (`Plc Logic`, `Task Configuration`). The tool trusted the `Path` verbatim, so `project-view/` folders became localized (`Device/PLC逻辑/Application/...`) and, on import, `_find_child_transparent` — which matches against the English IDE object name — never resolved the localized segment, creating the object under a fallback root-level folder instead of its intended parent.
- Standard-container labels are now folded back to their canonical English form via a bounded locale-alias table (`cli/external_engine/_locale_aliases.py`). The snapshot reader normalizes `Path` segments so the on-disk tree is locale-independent, and container resolution compares names through a locale-independent key, so a localized path segment matches an English (or localized) live IDE object. The transparent "Plc Logic" hop is likewise no longer hardcoded to English.
- **English projects are unaffected**: English names are never in the alias table, so canonicalization is a strict no-op (same folders, same matches) — verified by the offline regression harness and the full unit suite.
- Known localized labels are currently seeded for zh-CN from the reported issue; additional locales and segments extend the table one entry at a time.

**Relative `cds-sync-folder` fix (GH #61):**

- A relative sync folder (`.\CDS\`, `./CDS`, `.`) failed with `[Errno 13] Access denied` on CODESYS SP18. The path is anchored against the project file's directory, but every call site looked the project path up as `["filename", "FileName", "FullName", "Path"]` — and IronPython attribute access is case-sensitive, so the canonical lowercase `path` attribute exposed by ScriptEngine was never tried. The relative folder stayed unanchored and was resolved against the CODESYS working directory, which is not writable.
- Project-path lookup is now centralized in `_project_file_path()` (`ide_daemon_state.py`) with lowercase `path` tried **first**, and all four duplicated call sites (`_get_sync_folder`, `project_info`, `_project_path`, CRC file discovery) delegate to it.
- When a relative folder genuinely cannot be anchored (project never saved / no path exposed), the daemon now fails loudly with an actionable message instead of falling through to a misleading "Access denied".
- Regression guard: `tests/unit/test_project_file_path.py` pins the lookup order, including the exact SP18 shape (only lowercase `path` present).

Reported and diagnosed by reibax-marcus in #61 / #62.

---

### Version 2.8.0 (2026-07-20)

**Text-first sync mode (opt-in, chosen at initialization):**

- New `sync_mode` project setting (`Project_options.py` checkbox "Text-first mode"). Selected on an **empty** sync folder and locked once `.dump/manifest.json` exists — recorded in the manifest, enforced by the options dialog, the options params API, and the engine itself (export/compare/import refuse a mismatched settings file). To switch modes, initialize a new empty sync folder.
- In text-first mode every ST projection is force-enabled, and the structural XML sidecars move out of the view into the tool-owned, git-ignored `.dump/xml/` mirror (manifest entries record `xml_root: "dump"`). A per-kind "Keep XML in view for:" list (`xml_in_view_kinds`, default `["visu"]`) keeps selected kinds' XML in the view and in Git; it can be changed at any time.
- `.st` files are first-class import input in text-first mode: edits are applied even when the manifest never registered the projection; a hand-made `.st` — with or without a sidecar `.xml` — becomes one text-driven create; on a fresh clone (no `.dump/`) the `.st` text is overlaid on a fresh IDE baseline, and objects missing from the IDE are recreated from text. Conflicts keep the existing ".st wins" policy. Unmanaged `.st` files are never deleted by export; entries with no editable artifact (mirror XML only) are never pushed back into the IDE.
- The Project Options dialog shows a **single derived-files list that follows the selected paradigm** instead of two lists at once: the "Text-first mode" checkbox is the selector, and the list beneath it swaps in place — XML-first shows the `.st`/`.csv` projection toggles ("Derived views"), text-first shows the per-kind "Keep XML in view" list. The two are mutually exclusive, so only the relevant one is displayed.

**Export overwrite protection (both modes):**

- Export no longer silently overwrites locally-modified view files. Interactive export shows a review dialog with two independent, opt-in checkboxes — "Overwrite my local changes" and "Remove the unmanaged derived files" — both off by default, plus Continue / Cancel. Headless, daemon, and direct engine invocations **skip** dirty files by default: the files keep their content, their previous manifest hashes are carried forward so the next import still sees the edits, and they are reported as "pending import" (`pending_import` in the daemon `sync_export_text` response, and in the export completion popup).
- Unmanaged derived (`.st`/`.csv`) files with no manifest entry are **kept by default** and reported (softly proposed for removal), not deleted. Removal is a separate opt-in: `--remove-orphans` (engine CLI) or `remove_orphans=true` (operation/daemon params); the daemon lists them as `removable_orphans`. Orphan removal is independent of dirty overwrite — `--overwrite-dirty` no longer deletes orphans.
- **Behavior change**: engine `export` without flags now runs in skip-dirty mode and no longer deletes orphan projection files. Pass `--overwrite-dirty` to regenerate locally-modified files and `--remove-orphans` to delete unmanaged derived files.
- New engine subcommand `check-dirty` writes `.dump/dirty_report.json` (dirty managed files + would-be-removed orphans) without touching the view.

**Engine robustness (both modes):**

- The external engine no longer crashes when a diagnostic line contains non-ASCII characters — e.g. embedded-resource objects (`Resources/Embedded/*`) whose name is the original Cyrillic source path. On Windows the engine's stdout defaults to the legacy ANSI codepage (cp1252), so `compare` — the verb that logs per-object diff details — raised `UnicodeEncodeError` and exited non-zero, which the daemon surfaced as a bare `external engine compare failed`. Engine stdout/stderr are now forced to UTF-8 at startup (`errors="replace"`), matching how the daemon already reads them.

---

### Deprecated

The following CLI aliases are retained for backwards compatibility but are scheduled for removal in **3.0.0**:

- `cts rp` — deprecated alias for `cts raw`.
- `cts validate` — deprecated alias for `cts engine validate`.
- `cts resources` — deprecated alias for `cts engine resources`.

---

### Version 2.7.0 (2026-07-10)

**New / fixed CLI commands (previously non-functional):**

- `cts project open`, `close`, `list`, `list-devices`, `simulate`, `set-credentials`, `diagnose-online`, and top-level `cts discover` now work against the reverse-pipe daemon. These eight methods were sent by the CLI but had no daemon handler and returned `Unknown method: X` at runtime; they are now implemented and covered by a CLI↔daemon parity contract test.
- `cts project open` guards against reopening the already-open project and uses a longer timeout for large projects; `cts project close` uses a 60s timeout (a CODESYS modal save/disconnect dialog can still require manual dismissal).
- `cts project list` reports the primary project by path with a display-name fallback when the wrapper exposes no usable name.

**Sync import reliability (POUs/objects inside folders):**

- Native object import now succeeds for objects nested in folders. The embedded `ParentGuid` in an exported native payload is rewritten to the resolved container's live GUID before `import_native`, fixing the case where CODESYS refused the payload because the exported parent GUID no longer matched the live container.
- Native import is now resilient and diagnostic: a single object that CODESYS rejects no longer aborts the whole import. Failures are collected, reported per object under `failed_native_objects`, and the remaining objects still import.
- A name clash with an object in a different or nested folder (or a global-scope object) is now reported with a clear, located message instead of a generic rejection.
- The device object cache is invalidated after import so newly created objects are visible immediately.

**Daemon & online diagnostics:**

- `diagnose_online` now primes the online-app cache before reading the PLC snapshot, so the PLC section is populated without a prior explicit `app-state`/`connect` call.
- `SnapshotReader.read()` returns `None` instead of raising a `NameError` on a missing snapshot.

**CLI correctness:**

- Unknown CLI options now error with exit code 2 instead of being silently ignored (a typo such as `cts import --dry-runn` no longer runs a real import). `raw`/`engine` passthrough is unaffected.
- Legacy `cts project ...` commands now exit non-zero on failure, matching the daemon-command contract so scripting and CI see a truthful exit code.
- The hidden `project`/`pou` subcommand actions that duplicate a top-level command are now deprecated with a stderr warning pointing at the replacement.

**Visualization — experimental, not yet fully tested:**

- `cts visu from-svg` gained fill/stroke opacity support in SVG import. The SVG-to-visualization pipeline is still under active development and has **not** been fully validated end-to-end against the CODESYS visualization editor; treat it as experimental.

**Internal refactors & tech debt:**

- Extracted a shared discovery-report builder so forward-mode discover and the daemon `discover` handler share one implementation.
- Split the visualization builder into focused modules (`_builder_base`, `builder_frame`, `builder_inputs`) and separated `from_svg` into screen-create/append/GVL helpers.
- Split the offline regression runner into per-scenario functions and replaced repeated `sys.path` juggling with a single `_engine_on_path()` helper.
- Extracted CLI dispatch into per-area handler modules (`_cli_handlers_daemon`, `_cli_handlers_project`, `_cli_handlers_visu`).
- Fixed a latent path bug where build/discover ops computed the engine directory one level short after the `.runtime -> src/ide_bridge` move; added `ensure_engine_path()` as the shared resolver.
- Removed dead code and unused imports flagged during the cleanup pass.

**Packaging:**

- `setup.py` now ships every data file the code reads (`themes/*.json`, `styles_snapshot.json`, `stylesheet.css`, `DESIGN.md`, `external_engine/sys_funcs.json`) so a non-editable `pip install .` is complete (verified via wheel build).
- Added `cli.__version__` as the single source of truth and a `cts --version` command.

**Tests:**

- Added a CLI↔daemon method-parity contract test and a static daemon name-resolution guard that catches missing imports / unresolved globals in the IronPython daemon modules.
- Added end-to-end coverage for `commands.from_svg` and rewrote the integration smoke test as proper pytest functions.

---

### Version 2.6.1 (2026-06-15)

**CLI fixes from user feedback:**

- `cts import` now accepts `--force-online` to bypass the offline preflight check when `disconnect` does not fully clear CODESYS' online state, and `--dry-run` to preview changes with the same report as `compare`.
- `cts plc-crc` now accepts `--build` to compile the project before comparing CRCs.
- `cts write` now reads the value back and returns it under `read_back`, so callers can verify the write actually took effect.
- `cts engine` and the deprecated `validate`/`resources` aliases now accept `--timeout` for consistency with other commands; the value is ignored by the offline engine.
- `cts read-object` help now explains path format and recommends `--name` as the most reliable selector.
- `cts raw` help now mentions `force_online=true` and points to `cts raw help` for the method list.
- `cts test` help now references `cli/TEST_FORMAT.md`, and the "No .test/" error message includes format documentation pointers.

**Daemon fixes:**

- `_active_app_online_state` now prefers the cached `online_app` and only reports online when `is_connected` or `is_online` is true. It no longer falls back to a stale `application_state` string (e.g. `run`) after disconnect, which caused the documented `disconnect -> import` workflow to fail.
- `sync_import_text` now returns `skipped_projection_objects` in its output when modified objects have projection-only changes that cannot be applied automatically, making silent no-op imports visible.
- `variable-snapshot` JSON summary now includes a `failures` list with each failing path and error message.

**Documentation:**

- `cli/CLI.md` updated with `--force-online`, `--dry-run`, `--build`, `read-object` selector guidance, `raw` override examples, and improved test onboarding.

---

### Version 2.6.0 (2026-06-09)

**CLI Contract:**

- Added the short `cts` console alias alongside `cds-text-sync`.
- Simplified the primary CLI surface around the main user workflows: `ping`, `status`, `export`, `compare`, `import`, `build`, PLC lifecycle commands, variable commands, project/object tools, `raw`, and `engine`.
- Removed the separate `--manual` mode in favor of one short but explicit `cts --help` output.
- Renamed CLI documentation from `cli/MANUAL.md` to `cli/CLI.md` and the CI/CD test-format document to `cli/TEST_FORMAT.md`.
- Updated `cts --help` to document the operational model: folder, CODESYS IDE, and PLC are independent states; deployment moves data `folder -> IDE -> PLC`; folder-to-IDE import must be done while disconnected from the PLC.

**Daemon & PLC State:**

- `project-info` now returns CODESYS Project Information `summary` fields (`Company`, `Title`, `Version`, `Author`, `Description`, `DefaultNamespace`, `URL`) and all custom `properties`, including `cds-sync-folder`, `cds-daemon-config`, and `cds-sync-pc`.
- `ping` and `status` now include cached PLC state: `connected`, `online`, `running`, `application_state`, active application name, and application path. These commands do not auto-connect to the PLC.
- Fixed stale `online_app` cache handling so `connect -> plc-crc`, `device_status`, `start`, and `stop` work without first calling `app-state`.
- Closing the daemon window with the `X` button now requests daemon shutdown instead of leaving the script operation running and blocking the CODESYS UI.

**Import / Compare / Object Tools:**

- `sync_import_text` now updates existing `.st` text objects through the CODESYS text API when native XML import does not apply the changed POU body.
- `compare` now ignores XML serialization noise for externalized `.st`/`.csv` projections when the effective projection content matches the IDE content, including the `TextBlobForSerialisation` empty-container case.
- Added daemon support for `read_object`; `cts read-object --name MAIN` returns declaration, implementation, and object path.
- `update-pou` and `delete-pou` now default to the active CODESYS application instead of the previous hardcoded `CI_CD_Application`.

**Cleanup:**

- Removed legacy daemon/dead-code paths replaced by the reverse-pipe daemon flow.
- Removed unused daemon imports left after the reverse-pipe simplification.

**Release Verification:**

- Verified on a live CODESYS daemon test bench with a clean project state (`36/36 unchanged`) and daemon permissions open (`deny: []`).
- The daemon-driven `cts` workflow was exercised end to end across the main user-facing functions: `ping`, `status`, `permissions`, `raw`, `project-info`, `project-tree`, `export`, `compare`, `import`, `build`, `connect`, `disconnect`, `start`, `stop`, `app-state`, `plc-crc`, variable `read`/`write`, `variable-map`, `variable-snapshot`, `variable-restore`, `read-object`, `update-pou`, `delete-pou`, `read-log`, `sync`, `app_history`, `app_crc`, `app_info`, `create_boot_app`, `plc_upload`, JSON output, text output, and `--pretty`.

**Fixes:**

- Fixed creating `FUNCTION` POUs via `sync_import_text`: the return type is now parsed from the `FUNCTION name : <TYPE>` header and passed to the CODESYS `create_pou` API (handles `STRING(80)`, `ARRAY[..] OF X`, qualified user types, case-insensitive). Previously this crashed with `Specified argument was out of the range of valid values. Parameter name: return_type`. A clear error is raised if a FUNCTION has no return type.
- `sync_import_text` no longer aborts the whole import on a projection conflict. Policy is now **disk wins, `.st` is canonical**: when an object's raw XML projection and its `.st` text were both edited on disk, the `.st` text wins (overlaid on the IDE baseline) and the import continues with a warning. Export-only CSV/XML projection edits with no importer are skipped with a warning instead of failing.
- `sync_import_text` now fails early with a clear "disconnect first" error when the application has a live online session, instead of silently creating no objects. Override with `force_online`.
- `update_pou` now reports `impl_ok: true` with an `impl_skipped` note for objects that have no implementation section (GVL/DUT/interface), instead of a misleading `impl_ok: false`.

**CLI:**

- Added the top-level `read-vars EXPR ... [--file F]` command for batch-reading multiple variables/expressions. It sends a proper JSON list to the daemon, avoiding the `rp read_variables --names` pitfall where every value is passed as a raw string (`'names' must be a list`).

**Documentation:**

- `cli/CLI.md` documents sync direction (IDE/disk), the difference between raw XML snapshot import and text edits, the disk-wins conflict policy, and that `update_pou` is for single-object edge cases.

- Fixed UTF-8 handling in the IronPython reverse-pipe daemon for `.st` and JSON text reads, including `sync_compare_text` failing on IronPython 2.7 because builtin `open()` does not accept `encoding=`. Thanks to `kevin00156` for highlighting the bug.

---

### Version 2.5.1 (2026-05-28)

**CLI & Daemon:**

- Added the `cds-text-sync` CLI and reverse-pipe daemon workflow through `Project_daemon.py`.
- Added concise dashboard output for `rp cicd`: file-level PASS/FAIL plus suite summary.
- Changed the default CI/CD test folder from `test/` to `.test/`, with legacy `test/` fallback for existing projects.
- CI/CD plans now require an explicit `application` field so tests cannot silently run against the wrong application.
- Fixed `Project_options.py` runtime imports after moving the Python 3 engine to `cli/external_engine/`.
- Updated the recommended `.gitignore` entries for `.dump/`, reports, logs, backups, and temporary diff files.

**Installation & Documentation:**

- IRM installer now validates that `python --version` works and reports Python 3 before installing the CLI.
- IRM installer now offers to install the system CLI with `python -m pip install -e <install-path>`.
- Documentation now states that copying files into CODESYS `ScriptDir` does not install the `cds-text-sync` shell command.
- README and manuals refreshed for the CLI workflow, daemon demo, and test runner behavior.

**Infrastructure & Quality:**

- **GitHub Actions CI**: Added continuous integration workflow running tests on pushes and pull requests.
- **Node 24 Update**: CI actions updated to target Node 24 runtime.
- **Unit Test Tier**: Introduced structured unit test suite for external engine components.
- **Test Fixtures**: Unignored fixtures directory to include test data in version control.

**Security & Settings Window:**

- WinForms Settings window (poll frequency slider + permissions checkboxes)
- `rp permissions` — read-only config via CLI
- Storage in `cds-daemon-config` project property (JSON)
- Default deny list: reset_plc, create_boot_app, plc_upload, source_download
- Only the Settings window (not CLI) can change permissions
- Startup messages in dashboard (version + sync folder status)

**Fixes:**

- Stop Daemon no longer freezes CODESYS (Application.Exit, early loop break)
- Settings/Stop buttons swapped for ergonomics
- Sync folder warning on daemon start
- `run_external_engine()` path fixed to `cli/external_engine/`

**User Experience:**

- **Reference Compare Preview**: Validation now shows a reference comparison before applying changes.

**Documentation:**

- **Zed Extension**: Mentioned the Zed Structured Text extension for users who prefer the Zed editor.

### Version 2.0.1 (2026-05-11)

**Ambiguous Textual Object Projections:**

- **TypeGuid ST Pragmas**: Added `(* cds-text-sync: TypeGuid="{...}" *)` metadata pragmas for textual projections whose CODESYS object type cannot be reconstructed from ST syntax alone.
- **Persistent Variables Projection**: Persistent variable lists can now be exported and edited as `.st` projections while the sync pragma is stripped before XML rehydration and IDE text updates.
- **Profile-Driven GUID Policy**: Added `create_type_guids` and `ambiguous_text_type_guids` profile sections so special textual object handling is configured outside hardcoded syntax detection.
- **Textual Create TypeGuid**: `CreateTextObject` patch entries can now carry an explicit `TypeGuid`, preferred by the IDE bridge before built-in fallback GUID candidates.
- **Persistent Variables Safety Guard**: Creating a second Persistent Variables object in the same application is rejected before IDE apply because CODESYS supports only one such object per application.
- **IDE Bridge Cleanup**: Removed noisy create fallback diagnostics and the native XML template create fallback; existing textual objects are updated through available text documents even when CODESYS does not expose reliable `has_textual_*` flags.
- **Completion Summary Option**: Export and import now show a final success popup by default, with a project option to disable these completion summaries.

### Version 2.0.0 (2026-04-29)

**XML-First Synchronization Core:**

- **Native XML Snapshot Contract**: Reworked the sync flow around a fresh CODESYS Native XML snapshot for every export, compare, and import operation.
- **External Python 3 Engine**: Moved comparison, folder modeling, patch building, profile handling, and diagnostics out of the IDE bridge and into `src/external_engine/`.
- **Thin CODESYS Bridge**: Reduced IDE-side scripts to snapshot export, external engine dispatch, targeted text API updates, and native XML patch application.
- **Semantic XML Compare**: Added normalization for CODESYS serialization noise such as volatile timestamps, generated IDs, dictionary ordering, and whitespace.
- **Mixed Patch Application**: Textual POUs are now applied through CODESYS text APIs before native XML patch import handles remaining non-textual objects, preserving child method/action/property bindings.

**Public Script Set:**

- **User-Facing Commands**: Stabilized the public root entrypoints as `Project_directory.py`, `Project_options.py`, `Project_export.py`, `Project_import.py`, `Project_compare.py`, and `Project_compare_ui.py`.
- **Diagnostics Commands**: Added `Project_build.py`, `Project_discover.py`, and `Project_resources.py` for build checks, environment/type discovery, and snapshot resource analysis.
- **Hidden Engine Helpers**: Kept patch builders, project models, and runtime internals behind the `Project_*.py` scripts and external engine CLI.
- **Legacy Archive**: Preserved older scripts under `old_scripts/` for reference while making the new XML-first workflow the active path.

**Project Layout & Settings:**

- **Project Settings File**: Added tracked `cds-text-sync.json` support for layout, profile, and projection choices.
- **View Root Modes**: Added support for legacy `.dump/views`, default `project-view/`, explicit `--view-root`, and experimental root-view mode.
- **Generated State Separation**: Standardized generated folders around `.dump/`, `.backup/`, and `.diff/`, with stale managed files cleaned by manifest ownership.
- **Options UI**: Reworked `Project_options.py` so users can choose layout, active CODESYS profile, and optional derived text projections from a dialog.
- **Pre-Import Safety Backups**: Added optional timestamped `.project` backups before IDE-changing imports, stored only in `.backup/` with retention cleanup.

**Optional Text Projections:**

- **Readable POU `.st` Views**: Added opt-in `.st` projections for POU text with declaration first, `// --- implementation ---`, and implementation second.
- **Flat Child POU Files**: Added `.st` projections for methods, actions, properties, and accessors as sibling files such as `ST_FB.ST_METHOD.st`.
- **DUT `.st` Views**: Added declaration-only `.st` projections for DUT objects such as structures, enums, unions, and aliases.
- **Standalone `.st` Creates**: Added controlled creation of new text objects from standalone `.st` files when the semantic kind can be detected.
- **Text List CSV**: Added import-safe CSV projections for TextList objects, limited to editing existing rows and translations.
- **Alarm Item CSV**: Added import-safe CSV projections for alarm items, limited to existing alarm row updates.
- **No Duplicate PR Diffs**: When projections are enabled, export externalizes owned text into `.st` or `.csv` and redacts the duplicate text from the XML sidecar.
- **Projection Conflict Detection**: Compare/import now fail explicitly when both canonical XML and its derived projection changed since the last export.

**Compare & Review Workflow:**

- **Interactive Compare UI**: Added checkbox review, object metadata, and disk-vs-IDE diff viewing through `Project_compare_ui.py`.
- **Projection-First Diffs**: Compare UI prefers `.st` or `.csv` diffs when a projection owns the edited text, while keeping XML available for fallback cases.
- **Selected Actions**: Added filtered import/export support by GUID so Compare UI can apply only checked objects.
- **Large Project Stability**: Reduced compare report memory pressure and avoided flooding IDE output with repeated missing-resource messages.

**Diagnostics & Large Project Support:**

- **Build Diagnostics**: `Project_build.py` builds the active or selected application and writes `.dump/build_<Application>.log` plus `.dump/build_report.json`.
- **Discover Diagnostics**: `Project_discover.py` records live IDE tree/type information into `.dump/discover_tree.log` and `.dump/discover_report.json`.
- **Resource Diagnostics**: `Project_resources.py` analyzes snapshot object sizes and categories, writing `.dump/resources_report.json` and `.dump/resources_top.log`.
- **Missing External Resource Skip**: Snapshot export skips missing image/file-like resources that can block CODESYS native export on large projects.

**Known Limitations:**

- Visualization objects can report native import success while specific visual property edits are not applied by CODESYS; this remains a targeted investigation area.
- CSV projections are update-only in this release: inserted, removed, renamed, or duplicate rows fail explicitly.
- Graphical CFC/FBD/LD implementations are intentionally excluded from `.st` projections unless a profile explicitly marks a safe textual representation.

### Version 1.7.5 (2026-04-17)

**Profiles, Semantic Kinds & Sync Policy:**

- **JSON Type Profiles**: Added profile files in `profiles/` with inheritance, `guid_aliases`, `context_rules`, `sync_profile_overrides`, and `sync_direction_overrides` so projects can remap, merge, force XML handling, or skip types without code changes.
- **Semantic-First Type Resolution**: Completed the migration from scattered GUID checks to centralized semantic kind resolution, making object classification more consistent across export, compare, import, and discovery.
- **Per-Type Direction Control**: Added `bidirectional`, `export_only`, `import_only`, and `disabled` sync direction policies per semantic kind.
- **Library Manager as Export-Only**: `library_manager` now exports for Git visibility and diffing, but is skipped on import to avoid unreliable placeholder restoration.
- **Hardware Policy in Profiles**: `device` and `device_module` are now controlled by profile settings instead of hardcoded skips, using `native_xml` + `export_only` by default.
- **Profile Documentation**: Reworked profile docs into `profiles/profiles.md` and added a reusable `profiles/template.json`.

**Runtime Architecture & Entry Points:**

- **Internal Runtime Extraction**: Moved internal engine modules into `.runtime/` and reduced the top-level `Project_*` scripts to thin entrypoints.
- **Shared Bootstrap Layer**: Centralized runtime loading into a shared bootstrap module and renamed the public bootstrap entrypoint to `cds_bootstrap.py`.
- **Automation-Friendly Script Calls**: Updated the main entry scripts so they can be invoked more cleanly by external tooling and scripted workflows.

**Compare/Import Robustness:**

- **Nested ST Import Order Fix**: Import now sorts textual files so parent POUs are created before nested children like `TaskMain.Method.st`, fixing first-pass import into empty projects.
- **Shared Native XML Snapshot Path**: Export and compare now use the same native XML snapshot builder and the same recursion policy for XML-based objects.
- **Reduced False Hardware Diffs**: Folder hash invalidation is now limited to the direct parent folder, preventing one `.st` edit from forcing untouched `device` and `task_config` objects into noisy XML re-compare.
- **Cache Recovery for Exported Objects**: Added export-side cache backfilling and better cache warnings so successfully exported objects are less likely to disappear from `sync_cache.json` bookkeeping.
- **More Explainable Compare Logging**: Compare now logs the exact reason an object dropped into slow-path XML comparison.

**Logging, UI & Runtime Noise Reduction:**

- **Toggleable File Logging**: Added a project setting to enable or disable file logging and updated ignore patterns accordingly.
- **Quieter Compare/Import/Export Output**: Reduced console/log spam in normal workflows and removed compare log teeing to `compare.log`.
- **Settings Dialog Cleanup**: Refined the Settings UI layout and grouping for a cleaner configuration flow.
- **Unsupported Build Property Silence**: Missing `build_properties` members such as `external_implementation` are now skipped quietly instead of spamming `INFO`/`WARNING` for every object.
- **Python 3 Compatibility Cleanup**: Replaced deprecated `callable()` usage in runtime diagnostics with a Python-3-compatible check.

### Version 1.7.4 (2026-04-11)

**Attribute Synchronization (DRY Sync):**

- **Pragma-Based Metadata**: Implemented a new synchronization system for IDE-specific attributes (e.g., "Exclude from build", "Link always") using `//% cds-text-sync.key=value` pragmas directly in `.st` files.
- **CODESYS API Fixes**: Resolved issues with attribute access by correctly utilizing the `obj.build_properties` (ScriptBuildProperties) API for reading and writing IDE flags.
- **Bi-directional Sync**: Ensured that removing a pragma from the source file correctly clears the corresponding attribute in the IDE during import.
- **Cache Integrity**: Updated the quick hashing logic to include object attributes, ensuring that toggling IDE flags correctly invalidates the cache and triggers a re-export.
- **Comparison UI Enhancement**: The built-in diff viewer now renders IDE attributes as pragmas, allowing users to see and review metadata changes alongside code changes.
- **Cache Migration**: Bumped `CACHE_VERSION` to `3.1` to force a clean state rebuild and ensure all objects are tracked with attribute-aware hashes.

### Version 1.7.3 (2026-04-02)

**Move/Rename Detection & Stale File Cleanup:**

- **Moved File Detection**: Implemented smart detection of renamed/moved project files by cross-referencing IDE orphan objects with disk orphan files using base filename matching.
- **Automatic Path Invalidation**: Enhanced cache invalidation logic to detect when objects are moved/renamed in the IDE, ensuring stale cached paths are refreshed during comparison.
- **Stale File Cleanup**: Added automatic removal of old files from disk during export when objects have been moved/renamed in the IDE, preventing orphaned files from cluttering the sync directory.
- **UI Enhancements**: Updated comparison dialog to display moved files with their old (IDE) and new (Disk) paths, using `~moved` visual indicator.
- **Import/Export Move Handling**: Added logic to physically move objects within the IDE during import when path mismatches are detected, ensuring project structure stays synchronized.
- **Statistics Update**: Moved object count now reported in comparison summary (`~:` prefix) and import/export completion messages.

### Version 1.7.2 (2026-03-28)

**Critical Fixes & UX Optimization:**

- **Module Import Fix**: Resolved a critical `ImportError` where `codesys_ui` was not being loaded in `Project_directory.py`, causing a crash on startup for new projects.
- **Reference Bug Fixes**:
  - Fixed an undefined variable crash (`choice[0]`) in `Project_directory.py`.
  - Fixed an undefined variable crash (`result[0]`) in `Project_export.py` during orphaned file cleanup.

### Version 1.7.1 (2026-03-27)

**UI Robustness & Post-Sync Enhancements:**

- **Standard Windows Prompts**: Replaced the unreliable native CODESYS `system.ui.choose` radio-button dialogs with standard Windows MessageBox dialogs (`ask_yes_no`, `ask_yes_no_cancel`) across all scripts.
- **Cancel Button Fix**: Completely resolved an issue where clicking "Cancel" or closing dialogue windows would fail to halt script execution due to inconsistent CODESYS API return types.
- **Import Final Confirmation**: Added an explicit final summary dialog (`Ready to import X changes into the IDE... Proceed?`) right before applying structural changes or deletions in `Project_import.py`.
- **Auto-Save & Workflow**:
  - Introduced optional automatic project saving and binary backup after an export is completed.
  - Added a new 'Save Project after Export' toggle in the Configuration UI (`Project_parameters.py`).
  - Centralized version compatibility checks, safety backups, and post-sync operations into `codesys_utils.pyw` for cleaner architecture and standardized execution.

### Version 1.7.0 (2026-03-27)

**Merkle Tree & High-Performance Sync Overhaul:**

- **Lightning-Fast Comparison**: Total sync/compare time reduced by ~90% (sub-10s for large projects) using a new Merkle Tree-based hierarchical hashing strategy.
- **Intelligent Path/Type Caching**:
  - Implemented GUID-based caching for object classification and filesystem paths in `sync_cache.json`.
  - Eliminates thousands of slow CODESYS COM API calls (`classify_object`, `get_children`, `build_expected_path`) on repeat runs.
- **Hierarchical Merkle Skips**: The comparison engine now uses folder hashes to skip entire unchanged branches of the project tree instantly.
- **Import Optimization**:
  - Eliminated redundant double-save operations during import/backup, reducing the post-import pause by 50%.
  - Optimized POU child restoration and metadata handling.
- **Hybrid XML Hashing**: Integrated last-known XML hashes into Pass 1 so folders containing mixed ST and XML objects can still benefit from Merkle Tree skips.
- **Integrated Accessor Collection**: Merged property accessor scanning into the main object pass to avoid redundant project-wide traversals.
- **Profiling Tool Upgrade**: Updated `Project_perf_test.py` with the new architecture to provide accurate real-world metrics, including cache hit ratios and Merkle skip statistics.

---

### Version 1.6.7 (2026-03-25)

**Silent Mode Removal & Backup Enhancement:**

- **Removed Silent Mode**: All `silent` parameters have been removed from `Project_import.py`, `Project_export.py`, `Project_compare.py`, and `Project_Build.py`. Scripts now consistently use modal dialogs for all user feedback.
- **Unified UI Behavior**: All operations now use modal dialogs (`system.ui.info` / `system.ui.error`) in interactive mode, eliminating the previous inconsistent behavior.
- **Version Compatibility Checks**: All version compatibility checks now always prompt the user when version mismatches occur, rather than silently logging warnings or ignoring the issue.
- **Timestamped Backup with Retention**: Enhanced import backup functionality with automatic retention policy:
  - **codesys_utils.pyw**: Added `cleanup_old_backups()` function to automatically delete old timestamped backups while preserving non-timestamped Git LFS backups
  - **Enhanced Backup Function**: `backup_project_binary()` now accepts `retention_count` parameter and returns the backup filename on success
  - **UI Enhancement**: Added "Max Backups to Keep (Optional)" field in settings dialog (default: 10, minimum: 1)
  - **Persistent Settings**: Added `cds-sync-backup-retention-count` property to Project_parameters.py for cross-run persistence
  - **Import Scripts**: Both `Project_import.py` and `Project_compare.py` now create timestamped backups before import operations when changes exist
  - **Backup Reports**: Import completion reports now show backup confirmation message when safety backups are created
  - **Cleanup Pattern**: Only timestamped `.bak` files matching pattern `^\d{8}_\d{6}_.*\.bak$` are subject to cleanup; non-timestamped backup files are preserved

---

### Version 1.6.6 (2026-03-18)

**Resource Analysis UI Enhancement:**

- **Interactive Results Dialog**: `Project_resources.py` now displays results in a modern Windows Forms dialog instead of console output.
- **Sortable Data Grid**: Click column headers to sort by Object Name, Type, Size, or Category.
- **Full Object List**: Shows all analyzed objects with scrolling support (previously limited to top 30).
- **Summary Panel**: Displays Total Code, Total XML, and Object count at the bottom.
- **Fallback Support**: Console output still works if UI components are unavailable.

---

### Version 1.6.5 (2026-03-17)

**Interface Export Support:**

- **Interface Objects**: Added full support for exporting and importing `INTERFACE` objects with their `EXTENDS` clauses preserved.
- **Interface Methods**: Interface methods/properties now export as flat files (`InterfaceName.Method.st`) matching the existing FB pattern.
- **Native XML Fallback**: Added `export_interface_declaration()` function that extracts interface declarations via native XML export when `textual_declaration` is unavailable.
- **Updated Type GUIDs**: Corrected interface type GUID to `6654496c-404d-479a-aad2-8551054e5f1e` and added `itf_method` GUID for interface members.

---

### Version 1.6.4 (2026-03-12)

**UI Cleanup & Module Security:**

- **Hidden Internal Modules**: Renamed all `codesys_*.py` files to `.pyw` extension. This hides them from the CODESYS Script Engine menu, providing a cleaner user interface that only shows primary `Project_*.py` commands.
- **Custom Module Loader**: Implemented a robust `_load_hidden_module` mechanism in all entry scripts to handle `.pyw` imports with proper dependency ordering.
- **Deprecated Scripts Cleanup**: Removed several unused and debug scripts (`debug_metadata.py`, `Project_Daemon.py`) to streamline the repository.

---

### Version 1.6.3 (2026-03-07)

**Version Tracking & Compatibility Detection:**

- **Single Source of Truth**: Added `SCRIPT_VERSION = "1.6.3"` in `codesys_constants.py` as the central version reference for all scripts.
- **Dual Storage Strategy**:
  - **sync_metadata.json**: Metadata file stored in export directory containing script version, last action (export/import), timestamp, duration, and statistics.
  - **Project Property**: Version also saved to CODESYS project property (`cds-sync-version`) for runtime compatibility checks.
- **Import/Compare Warnings**: Both `Project_import.py` and `Project_compare.py` now detect version mismatches and display warnings without blocking operations (User can continue at their own risk).
- **Improved Audit Trail**: Each export and import operation updates `sync_metadata.json` with current script version, making it easy to identify which scripts were used for operations.
- **Git Integration**: The `sync_metadata.json` file is now tracked in version control, enabling teams to see export/import history.

---

### Version 1.6.2 (2026-03-04)

**XML Import & Object Structure Enhancements:**

- **POU Child Management**: Implemented saving and restoring of POU children during the XML import process to maintain project hierarchy.
- **Parent Lookup**: Enhanced parent POU lookup logic during object creation for improved structural accuracy.
- **Empty Implementation Handling**: Ensured that implementation markers are always present for specific object types, even if their implementation is empty (addressing issues where empty methods or properties might be skipped).

### Version 1.6.1 (2026-02-26)

**Orphan Deletion & Stability Enhancements:**

- **Bi-directional Orphan Management**:
  - **IDE-to-Disk (Sync/Export)**: Existing logic in `Project_export.py` continues to clean up files on disk that are missing in the IDE.
  - **Disk-to-IDE (Import)**: `Project_import.py` now supports deleting objects from the IDE if they were removed on disk (e.g., from a Git pull). The "Disk wins" principle is now fully enforced.
- **Improved Comparison UI**:
  - The Interactive Results dialog now clearly identifies objects missing on disk as **"Missing on Disk (DELETE from IDE?)"**.
  - Importing these items will now safely remove them from the CODESYS project tree.
- **Hardware Stability (Device Exclusion)**:
  - Hard-excluded `device` and `device_module` objects from the synchronization engine.
  - Syncing these components via XML was found to be unstable (can lead to tree reconstruction and project "emptying").
  - Users should configure hardware manually and sync the application logic.
- **Bug Fixes**:
  - Fixed an issue where the import process could fail to report the correct number of updated/created items when deletions were involved.
  - Updated default `.gitignore` template to include `*.device` and `*.device_xml` patterns as a safety measure.

### Version 1.6 (2026-02-24)

**Core Engine Refactoring & Interactive Sync:**

- **Multi-PLC & Multi-Application Support**: The engine now automatically handles complex project hierarchies, organizing exports into a clear `Device/Application/Folder` structure (essential for modern CODESYS projects).
- **Metadata-Free Sync Engine**: Significant refactoring to transition from metadata files (`_metadata.csv`, `_config.json`) to a direct, hash-based two-way comparison between the CODESYS IDE and disk. This improves reliability when moving projects between machines or using Git.
- **Interactive Comparison Dialog**: `Project_compare.py` now includes an interactive results window where you can selectively apply changes (Import or Export) directly from the diff list.
- **Project Discovery Tool**: New `Project_discover.py` script for mapping the project tree structure and diagnosing supported block types (logs findings to `sync_debug.log`).
- **Maintenance**: `Project_daemon.py` has been temporarily disabled.
- **Improved Comparison Logic**: Better handling of graphical POUs and XML-based objects (Visualizations, Task Configurations) in the comparison engine.

### Version 1.5.6.1 (2026-02-21)

### Version 1.5.6 (2026-02-18)

**Safety Net: Timestamped Import Backups:**

- **Automatic Rollback Point**: `Project_import.py` now creates a timestamped backup (e.g., `20260218_220000_MyProject.project.bak`) at the very beginning of the import process.
- **Configurable Safety**: Added "Timestamped Backup before Import" toggle in `Project_parameters.py` (enabled by default).
- **Non-destructive**: These backups are placed in the `/project` folder and use a `.bak` extension to avoid conflict with your primary Git LFS tracking.

### Version 1.5.5 (2026-02-18)

**Relative Path Support for Team Collaboration:**

- **Portable Project Configuration**: `Project_directory.py` now supports relative paths (e.g., `./`, `./folderName/`) in addition to absolute paths.
- **Manual Path Input**: Added a new "Manual Input" option in the directory setup dialog, allowing users to type paths directly.
- **Automatic Directory Creation**: If a specified directory doesn't exist, it will be created automatically.
- **Team-Friendly**: Relative paths are resolved relative to the project file location, making projects portable across different machines and users without reconfiguration.
- **Examples**:
  - `./` - Sync to project directory
  - `./sync/` - Sync to a subfolder
  - `C:\MySync\` - Traditional absolute path still supported

### Version 1.5.4 (2026-02-16)

**Comparison Logging & Rerouting:**

- **Dedicated Comparison Log**: `Project_compare.py` now reroutes its output to `compare.log` in the sync directory.
- **Recreative Logging**: The log file is truncated and recreated on every run, providing a fresh report for each comparison.
- **Tee Output**: Comparison results are still mirrored to the CODESYS Script Output window for immediate feedback.

### Version 1.5.3 (2026-02-16)

**Line Ending & Git Consistency Fix:**

- **Cross-Platform Consistency**: Fixed an issue where different line endings (CRLF vs LF) on different machines caused Git to show identical files as modified.
- **Deterministic Export**: The export script now explicitly uses LF (`\n`) for all `.st` files regardless of the host OS by using `newline=''` in file operations.
- **Automated Git Configuration**: Updated the `.gitattributes` template to automatically disable text conversion for `.st` files (`*.st -text`), ensuring they remain as LF in the repository and are treated consistently by Git on all platforms.

### Version 1.5.2 (2026-02-15)

**Improved Property Sync & Bug Fixes:**

- **Enhanced Property Support**: Properties with combined GET/SET accessors are now correctly handled. The export script now accurately combines both the `VAR` declaration and implementation code for each accessor into a single `.st` file.
- **Bi-directional Accessor Sync**: The import script now correctly parses combined accessor content and updates both the declaration and implementation in CODESYS.
- **Object Restoration**: Fixed an issue where objects deleted from CODESYS but remaining on disk would not be recreated. They are now automatically detected and restored during import.
- **Bug Fix (#4)**: Resolved an issue where properties created manually in external editors were incorrectly identified or failed to import.

### Version 1.5.1 (2026-02-15)

**Performance & Optimization Update:**

- **CRC32 Hashing**: Switched from SHA256 to CRC32 for file tracking, achieving **10-20x faster** hashing performance and significantly reducing metadata size.

### Version 1.5.0 (2026-02-13)

**The "Power User" Update:**

- **Project_Daemon.py**: New background service with Global Hotkey (`Alt + Q`).
- **Quick Action Dashboard**: Instant access to Export, Import, Build, and Backup commands.
- **Enhanced Build Log**: `Project_Build.py` now generates a clean, readable table format in `build.log` with accurate line numbers for external editors.
- **Focus Management**: Daemon correctly handles focus switching between Virtual Desktops and restores context after execution.

### Version 1.4.0 (2026-02-12)

**UI & Experience Overhaul:**

- **Configuration Dialog**: Replaced the text-based menu with a modern Windows Forms dialog for easier configuration.
- **Silent Mode**: Added a "Silent Mode" option that uses non-blocking system tray notifications (toasts) instead of blocking popups.
- **Safety**: Added checks to prevent sync on wrong machine (PC Name check).

### Version 1.3.0 (2026-02-09)

**Binary Backup & Configuration Overhaul:**

- **Project_parameters.py**: New interactive menu to toggle features.
- **Binary Backup**: Added optional `.project` file backup loop. The binary is now updated on both Export and Import events.
- **Logging**: Moved `sync_debug.log` to the project sync folder (or Temp) to keep `ScriptDir` clean.
- **Import Logic**: Removed interactive menu from Import script; now uses project settings.

### Version 1.2.0 (2026-02-09)

**Safety & Validation:**

- **PC Check**: Validates `cds-sync-pc` to prevent syncing on the wrong machine.
- **Properties**: All settings are now stored in Project Properties (`cds-sync-*`).

### Version 1.0.0 - 1.1.0

- Full support for nested folders.
- Detection of deletions (Orphan cleanup).
- Library version tracking (`_libraries.csv`).
