# cds-text-sync: Professional CODESYS Git Sync

[![CI](https://github.com/ArthurkaX/cds-text-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/ArthurkaX/cds-text-sync/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/ArthurkaX/cds-text-sync?include_prereleases&sort=semver)](https://github.com/ArthurkaX/cds-text-sync/releases)
[![Forks](https://badgen.net/github/forks/ArthurkaX/cds-text-sync)](https://github.com/ArthurkaX/cds-text-sync/forks)
[![Issues](https://img.shields.io/github/issues/ArthurkaX/cds-text-sync)](https://github.com/ArthurkaX/cds-text-sync/issues)
[![License](https://img.shields.io/github/license/ArthurkaX/cds-text-sync)](LICENSE)

**Version**: `2.8.3`

> [!IMPORTANT]
> **Disclaimer**: This is a third-party tool. It is NOT an official product of CODESYS Group and is not affiliated with, sponsored by, or endorsed by CODESYS Group. This tool is provided "as is" and is not a replacement for official CODESYS products.

Review and edit CODESYS projects with normal Git tools, external editors, and
automation. CODESYS exports a fresh Native XML snapshot, the external Python 3
engine builds an editable project view on disk, and your edits are applied back
through targeted CODESYS text APIs plus native XML patches.

- **XML-first** (default): native XML in the view root is the canonical
  round-trip format; optional `.st` and `.csv` projections make code and
  translations readable in normal PR diffs.
- **Text-first** (opt-in): `.st` files become the editable surface and the
  structural XML is hidden in a tool-owned `.dump/xml/` mirror — for teams and
  LLM workflows that treat the text on disk as the source of truth.

See [Sync modes](docs/sync-modes.md) for the choice, which is made once per sync
folder.

> [!TIP]
> **Using this tool? There is a place to say what you think of it.**
>
> This project is built almost entirely from user reports — relative paths, localized IDEs, nested methods,
> visualizations and library placeholders were all fixed because somebody said something.
>
> Not everything worth saying is a bug report, though. If you have an opinion on where the tool should go,
> a workflow it does not fit, or a question about whether something is intended —
> **[come say it in Discussions](https://github.com/ArthurkaX/cds-text-sync/discussions)**. No format required.
>
> And if something simply feels awkward to use, there is a
> **[form for exactly that](https://github.com/ArthurkaX/cds-text-sync/issues/new?template=3-friction.yml)** —
> no reproduction steps, no version numbers, half a sentence is enough.

---

## 🚀 Quick start

**Requirements**: CODESYS V3.5 SP10+ (SP13 and newer recommended) and Python 3
available as `python` on the command line. Full list in
[Installation](docs/install.md#requirements).

Install into the CODESYS script directory with one command:

```powershell
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

Then, in CODESYS, from **Tools > Scripting > Scripts > P**:

1. **`Project_directory.py`** — link the open project to a folder on disk.
2. **`Project_options.py`** — pick the sync mode, layout, profile, and which
   `.st`/`.csv` projections you want.
3. **`Project_export.py`** — write `.dump/IDE.xml` and build the editable view in
   `project-view/`.
4. **Edit** the files in `project-view/` in any editor, and commit them.
5. **`Project_import.py`** — apply the disk edits back into CODESYS.
   (`Project_compare.py` / `Project_compare_ui.py` show you the difference first.)

The same cycle from a shell, once `Project_daemon.py` is running in the IDE:

```powershell
python -m pip install -e <cds-text-sync-folder>
cts export     # IDE -> project-view/
cts compare    # IDE vs project-view/
cts import     # project-view/ -> IDE
```

Details: [Installation](docs/install.md) · [Script overview](docs/scripts.md) ·
[Project layout](docs/project-layout.md) · [CLI reference](cli/CLI.md)

For Zed users, [`PLC Structured Text`](https://github.com/ArthurkaX/zed-plc-structured-text) provides IEC 61131-3 Structured Text syntax highlighting for the generated `.st` / `.iecst` projections, focused on CODESYS-style PLC projects.

---

## 🖥️ HMI screens from SVG

Draw the screen as an SVG sketch; `cts visu` compiles it into a CODESYS
visualization object. You never write a colour — an element carries
`class="panel"`, `class="h1"`, `class="pipe-water"`, and the palette resolves it
against the CODESYS visual style your project actually uses, in a light or a
dark scheme, from the same unchanged sketch.

```powershell
cts visu new --name Line1 --w 1024 --h 600 --out line1.svg   # laid-out skeleton
cts visu lint --svg line1.svg --fix                          # design check
cts visu preview --svg line1.svg                             # .preview.svg + .preview.png
cts visu from-svg --svg line1.svg --create-screen --screen-name Line1 --gvl VisuVars
cts import                                                   # into CODESYS
```

The sketch is text, so it diffs and reviews like the rest of the project. `new`,
`lint` and `preview` need no IDE and no project. `cts visu --help` prints the
whole SVG contract inline, which is enough for an LLM agent to author a screen
with no other documentation.

Full walkthrough — prerequisites, PLC variable binding, themes, the agent
workflow: **[HMI screens from SVG](docs/visu.md)**.

---

## 📚 Documentation

| Guide | What is in it |
| --- | --- |
| [Installation](docs/install.md) | Requirements, both install methods, CLI install, upgrading |
| [Sync modes](docs/sync-modes.md) | XML-first vs text-first, and overwrite protection |
| [Script overview](docs/scripts.md) | What each `Project_*.py` does, and the optional projections |
| [Project layout](docs/project-layout.md) | On-disk structure, `.gitignore`, the day-to-day cycle, Git LFS |
| [HMI screens from SVG](docs/visu.md) | `cts visu` end to end, including variable binding |
| [CLI reference](cli/CLI.md) | Every `cts` command, flag, timeout and error mode |
| [Team workflow](docs/workflow.md) | Branches and PRs for HMI/hardware engineers and developers |
| [Alternative installations](docs/alternative-installations.md) | Forks and non-standard CODESYS environments |
| [Releases & rollback](docs/releases.md) | Stable tags, version policy, reverting |
| [Profiles](profiles/profiles.md) | Vendor/fork object kinds, projection availability, safety rules |
| [SVG authoring contract](skills/cds-visu-svg/SKILL.md) | Layout rules and conventions an authoring model follows |

---

## 🚀 Key features

- **XML-First Export**: `Project_export.py` captures `.dump/IDE.xml`, refreshes the configured view root, and writes `.dump/manifest.json`.
- **Compare Reports**: `Project_compare.py` captures `.dump/IDE.current.xml` and writes `.dump/compare_report.json` without changing the open project.
- **Interactive Review**: `Project_compare_ui.py` shows object-level changes in CODESYS, supports diff viewing, and can apply checked import/export actions.
- **Patch Import**: `Project_import.py` builds `.dump/IMPORT.xml` from disk edits and applies textual objects through CODESYS text APIs before native XML import handles the rest.
- **Overwrite Protection**: local edits you have not imported yet are never silently overwritten, and unmanaged files are never deleted without asking.
- **Pre-Import Backups**: optional timestamped `.project` backups are written to `.backup/` before IDE-changing imports, with a configurable retention count.
- **Optional `.st` Projections**: POU, POU child, GVL, persistent variable list, task-local GVL, and DUT text can be emitted as readable `.st` files while duplicated text is removed from the XML sidecar for cleaner PR diffs.
- **Optional `.csv` Projections**: text lists and alarm items can be exported as CSV and imported back for existing-row edits such as translation updates.
- **Profile-Aware Behavior**: JSON profiles describe vendor/fork-specific object kinds, projection availability, and safety rules.
- **CLI + Reverse-Pipe Daemon**: `cts` controls a running CODESYS IDE through `Project_daemon.py` — build, online diagnostics, PLC file access and variable read/write, CRC checks, project lifecycle, and JSON-based test plans.
- **HMI Screens from SVG**: `cts visu` authors visualizations as SVG sketches — lint, preview and a light/dark colour scheme included — and compiles them into CODESYS visualization objects.
- **Diagnostics**: `Project_build.py`, `Project_discover.py`, and `Project_resources.py` provide build, environment, profile, and snapshot-size diagnostics, plus an offline static call graph via `cts engine call-tree`.

![CLI daemon demo](img/cli_demo.gif)

---

## 🧪 Reference project & examples

To keep this repository lightweight and minimalist for users who `git clone` the
scripts, all test cases, problematic objects, and compatibility examples are
hosted in a separate
**[Reference Project](https://github.com/ArthurkaX/cds-text-sync-reference-project)**.
Refer to that repository's README for detailed verification procedures and
contribution guidelines.

---

## 🗣️ Community & Feedback

This is a third-party tool maintained by one person, and nearly every feature and fix in the changelog
traces back to a user who took a few minutes to describe a problem. If you use it, you are in a better
position than anyone to say what should change.

**Pick whichever costs you the least effort:**

| I want to... | Where |
|---|---|
| Report something broken | [Bug report](https://github.com/ArthurkaX/cds-text-sync/issues/new?template=1-bug.yml) |
| Say what is confusing or tedious — *no repro needed* | [Friction report](https://github.com/ArthurkaX/cds-text-sync/issues/new?template=3-friction.yml) |
| Ask for something the tool cannot do | [Feature request](https://github.com/ArthurkaX/cds-text-sync/issues/new?template=2-feature.yml) |
| Ask whether something is a bug or expected | [Q&A discussion](https://github.com/ArthurkaX/cds-text-sync/discussions/categories/q-a) |
| Say something that is none of the above | [Discussions](https://github.com/ArthurkaX/cds-text-sync/discussions) |
| Influence a roadmap decision in one click | [Polls](https://github.com/ArthurkaX/cds-text-sync/discussions/categories/polls) |
| Just react to what is planned next | [Open roadmap issues](https://github.com/ArthurkaX/cds-text-sync/issues?q=is%3Aissue+is%3Aopen+label%3Aroadmap) |

> [!NOTE]
> **Discussions are open, and quieter than they should be.**
> If you have something to say that does not fit an issue — a doubt about the direction, a workflow this
> tool does not serve, an opinion on a decision that is being made — that is what
> [Discussions](https://github.com/ArthurkaX/cds-text-sync/discussions) are for. You do not need a proposal,
> evidence, or a solution. An objection with nothing behind it but experience is still worth reading.

Bug reports are usually resolved within a day or two. Reporters are credited by name in the changelog.
Corporate users: internal criticism is welcome here too — an anonymized "our team keeps tripping over X"
is more valuable than silence, and you do not need permission to describe a workflow problem.

---

## 📝 Changelog

See the full [CHANGELOG.md](CHANGELOG.md) for details on all versions, and
[GitHub Releases](https://github.com/ArthurkaX/cds-text-sync/releases) for
stable download links. Contributions: [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 📜 License

MIT License.
