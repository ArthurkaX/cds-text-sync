# cds-text-sync: Professional CODESYS Git Sync

[![CI](https://github.com/ArthurkaX/cds-text-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/ArthurkaX/cds-text-sync/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/ArthurkaX/cds-text-sync?include_prereleases&sort=semver)](https://github.com/ArthurkaX/cds-text-sync/releases)
[![Forks](https://badgen.net/github/forks/ArthurkaX/cds-text-sync)](https://github.com/ArthurkaX/cds-text-sync/forks)
[![Issues](https://img.shields.io/github/issues/ArthurkaX/cds-text-sync)](https://github.com/ArthurkaX/cds-text-sync/issues)
[![License](https://img.shields.io/github/license/ArthurkaX/cds-text-sync)](LICENSE)

**Version**: `2.8.3`

> [!IMPORTANT]
> **Disclaimer**: This is a third-party tool. It is NOT an official product of CODESYS Group and is not affiliated with, sponsored by, or endorsed by CODESYS Group. This tool is provided "as is" and is not a replacement for official CODESYS products.

## What this is

A CODESYS project is a single binary `.project` file. Git can store it, but it
cannot see inside: there is no diff, no line-by-line review, no way for two
engineers to merge their work, and no way for any external tool to read your
logic.

**cds-text-sync turns that project into a folder of files on disk** — one per
object, XML with optional readable `.st` and `.csv` text — which you keep in a
normal Git repository, review in pull requests, edit in any editor, and apply
back into the IDE. CODESYS stays the tool that talks to hardware; Git becomes
the tool that holds the history.

```
CODESYS project  ──export──►  project-view/ on disk  ──►  git commit, PR, review
      ▲                              │
      └──────────import──────────────┘
```

That is the core, and everything else in the tool is built on top of it. Once
the project is text on disk, things that were impossible become ordinary — which
is where the other two layers come from.

---

## The three layers

### 1. Git outside CODESYS — the core

Export the open project to disk, edit it anywhere, bring the edits back.

- **[`Project_export.py`](docs/scripts.md#4-project_exportpy-codesys---disk)** captures a full native snapshot to `.dump/IDE.xml` and rebuilds the editable view in `project-view/`.
- **[`Project_import.py`](docs/scripts.md#5-project_importpy-disk---codesys)** applies your disk edits back — textual objects through the CODESYS text APIs, the rest through native XML import — with an optional timestamped `.project` backup first.
- **[`Project_compare_ui.py`](docs/scripts.md#6-project_compare_uipy-ide-vs-disk)** reports what differs between the IDE and disk, as JSON and as a dialog inside CODESYS that can apply changes object by object.
- **[Text projections](docs/scripts.md#7-optional-projections)** make the code itself readable: POUs, their methods and actions, GVLs, persistent variable lists and DUTs as `.st`; text lists and alarm items as `.csv`. A logic change then shows up once, in the `.st` file, instead of twice in XML and text.
- **[Overwrite protection](docs/sync-modes.md#overwrite-protection-both-modes)** means export never silently discards a local edit you have not imported yet, and never deletes a file it does not own.
- **[Profiles](profiles/profiles.md)** describe vendor and fork-specific object kinds, which projections are available, and the safety rules — so a DIAStudio or KeStudio project behaves correctly rather than approximately.

Two paradigms, chosen once per sync folder: **XML-first** keeps native XML as the
canonical round-trip format with text projections beside it, and **text-first**
makes the `.st` files the source of truth and hides the structural XML in a
tool-owned mirror. See [Sync modes](docs/sync-modes.md).

### 2. CLI and daemon — automation, CI, and LLM agents

The scripts above live in the CODESYS **Tools > Scripting** menu and need a human
to click them. `Project_daemon.py` runs inside the IDE and exposes it over a
per-user Windows named pipe; the `cts` CLI talks to that pipe. Anything that can
run a shell command can now drive CODESYS — a CI job, a Makefile, or an LLM agent
working on its own.

```powershell
cts status                 # daemon / project / sync-folder / PLC state
cts export                 # IDE -> project-view/
cts import                 # project-view/ -> IDE
cts build                  # build the active application
cts test --file plan.json  # JSON-defined test plan
```

Beyond the sync cycle it covers build execution and logs, PLC connect / start /
stop / reset, variable read and write, variable map / snapshot / restore, PLC
file listing and transfer, application CRC for deployment verification, project
lifecycle (open, close, list devices, simulate, credentials, online
diagnostics), object-level read / update / delete, environment discovery, and
JSON or text output on every command.

This is the layer that makes autonomous work possible: an agent can read the
project, change it, build it, check the result, and iterate — without a person
in the loop clicking dialogs. See the **[CLI reference](cli/CLI.md)**.

### 3. `cts visu` — HMI screens authored by an LLM

The last thing in a CODESYS project that resisted text was the visualization.
`cts visu` closes that: you author the screen as an **SVG sketch** — text, so it
diffs and reviews like everything else — and the tool compiles it into a real
CODESYS visualization object.

![A sorting-line overview screen compiled from an SVG sketch](img/visu_preview.png)

The point is who writes the SVG. `cts visu --help` prints the entire contract
inline — supported tags, semantic classes, colour variables, what is
unsupported — so an LLM agent needs no other documentation to produce a valid
screen, and `lint` plus `preview` let it check its own work before anything
reaches the IDE. You never write a colour: an element carries `class="panel"` or
`class="value"`, and the palette resolves against your project's visual style, in
a light or a dark scheme, from the same unchanged sketch.

```powershell
cts visu new --name Line1 --w 1024 --h 600 --out line1.svg
cts visu lint --svg line1.svg --fix
cts visu preview --svg line1.svg
cts visu from-svg --svg line1.svg --create-screen --screen-name Line1 --gvl VisuVars
cts import
```

`--gvl` generates the GVL declarations for every PLC variable the screen binds,
so the screen arrives wired rather than referencing names that do not exist.
Full walkthrough: **[HMI screens from SVG](docs/visu.md)**.

---

## Quick start

**Requirements**: CODESYS V3.5 SP10+ (SP13 and newer recommended), Windows, and
Python 3 available as `python`. Full list in
[Installation](docs/install.md#requirements).

Install with one command — it sets up the tool, the CLI, and the CODESYS
scripting menu:

```powershell
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

Then, in CODESYS, from **Tools > Scripting > Scripts > P**:

1. **`Project_directory.py`** — link the open project to a folder on disk.
2. **`Project_options.py`** — pick the sync mode, layout, profile, and which
   `.st`/`.csv` projections you want.
3. **`Project_export.py`** — write the snapshot and build `project-view/`.
4. **Edit** the files in `project-view/` in any editor, and commit them.
5. **`Project_import.py`** — apply the disk edits back into CODESYS.

For layers 2 and 3, install the CLI and start the daemon:

```powershell
python -m pip install -e <program-folder>
cts --help
```

Details: [Installation](docs/install.md) · [Script overview](docs/scripts.md) ·
[Project layout](docs/project-layout.md) · [CLI reference](cli/CLI.md)

![CLI daemon demo](img/cli_demo.gif)

---

## Documentation

| Guide | What is in it |
| --- | --- |
| [Installation](docs/install.md) | Requirements, the three install methods, CLI install, upgrading |
| [Sync modes](docs/sync-modes.md) | XML-first vs text-first, and overwrite protection |
| [Script overview](docs/scripts.md) | What each `Project_*.py` does, and the optional projections |
| [Project layout](docs/project-layout.md) | On-disk structure, `.gitignore`, the day-to-day cycle, Git LFS |
| [CLI reference](cli/CLI.md) | Every `cts` command, flag, timeout and error mode |
| [HMI screens from SVG](docs/visu.md) | `cts visu` end to end, including PLC variable binding |
| [Team workflow](docs/workflow.md) | Branches and PRs for HMI/hardware engineers and developers |
| [Alternative installations](docs/alternative-installations.md) | Forks and non-standard CODESYS environments |
| [Releases & rollback](docs/releases.md) | Stable tags, version policy, reverting |
| [Profiles](profiles/profiles.md) | Vendor/fork object kinds, projection availability, safety rules |
| [SVG authoring contract](skills/cds-visu-svg/SKILL.md) | Layout rules and conventions an authoring model follows |

Diagnostics live in the CLI and the scripts alike: `Project_build.py`,
`Project_discover.py` and `Project_resources.py` write build, environment and
snapshot-size reports, and `cts engine call-tree` builds a static call graph
offline. For Zed users,
[`PLC Structured Text`](https://github.com/ArthurkaX/zed-plc-structured-text)
adds IEC 61131-3 syntax highlighting for the generated `.st` / `.iecst` files.

---

## Reference project & examples

To keep this repository lightweight for users who `git clone` the scripts, all
test cases, problematic objects, and compatibility examples are hosted in a
separate
**[Reference Project](https://github.com/ArthurkaX/cds-text-sync-reference-project)**.
Refer to that repository's README for detailed verification procedures.

---

## Community & Feedback

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
>
> And if something simply feels awkward to use, there is a
> [form for exactly that](https://github.com/ArthurkaX/cds-text-sync/issues/new?template=3-friction.yml) —
> no reproduction steps, no version numbers, half a sentence is enough.

Bug reports are usually resolved within a day or two. Reporters are credited by name in the changelog.
Corporate users: internal criticism is welcome here too — an anonymized "our team keeps tripping over X"
is more valuable than silence, and you do not need permission to describe a workflow problem.

---

## Changelog & License

See the full [CHANGELOG.md](CHANGELOG.md) for details on all versions, and
[GitHub Releases](https://github.com/ArthurkaX/cds-text-sync/releases) for
stable download links. Contributions: [CONTRIBUTING.md](CONTRIBUTING.md).

MIT License.
