# Onboarding: your first hour

This page walks the path once, in order, from a fresh install to a committed
first change. It assumes nothing except that CODESYS is installed. For the
reference detail behind each step, follow the links.

If you only want the four commands, the [README quick start](../readMe.md#1-quick-start)
is the short version.

---

## 1. Install

```powershell
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

The installer checks for Python 3.11+, puts the tool in a program folder, and
writes only the `Project_*.py` menu scripts into the CODESYS ScriptDir. It ends
by printing both paths. Run `cts where` later if you need them again.

Details, manual and Git-clone installs: [Installation](install.md).

## 2. Find the commands — the long way

Open your project in CODESYS and go to:

**Tools > Scripting > Scripts > P**

Everything this tool adds is there, and nothing of it is anywhere else in that
menu. Two things are worth knowing before you look:

- The commands are grouped under **P** because every name starts with
  `Project_`. That grouping is CODESYS behavior, not a setting.
- **The list is alphabetical, not in the order you use them.** `Project_analyze_ui`,
  `Project_build`, `Project_compare_ui` and `Project_daemon` all sort above
  `Project_directory` — which is the one you actually need first. Do not read the
  list top-down as a workflow.

If you run something out of order, nothing breaks: the commands that need a sync
folder stop with `Sync folder is not configured. Run Project_directory.py first.`

What each command does: [Script overview](scripts.md).

## 3. Find the commands — the short way

Four menu levels per action gets old fast, and export/import/compare are actions
you will run many times a day. Spend one minute now and put them on a toolbar:

**Tools > Customize > Toolbars**, then add the commands from
**ScriptEngine Commands > P**.

<details>
<summary><strong>▶ Click to open the animation: adding a quick-access button</strong></summary>

<p><img src="../img/add_button.gif"
   alt="Adding the Project_* scripts to a CODESYS toolbar"
   width="100%"></p>
</details>

Pin these four and leave the rest in the menu:

| Command | Why it earns a button |
|---------|----------------------|
| `Project_export` | CODESYS → disk, the most-repeated action |
| `Project_import` | disk → CODESYS, the other half of the cycle |
| `Project_compare_ui` | see what differs before you commit or import |
| `Project_analyze_ui` | findings view while you are still editing |

The buttons keep working after an upgrade, because the menu scripts keep their
names.

## 4. Link the project to a folder on disk

Run **`Project_directory.py`**. It asks for the sync root for *this* project and
saves it in the project properties.

![Setup Project Directory](../img/setFolder.gif)

Relative paths are worth using here: `./` puts the sync folder beside the
`.project` file, `./src/` in a subfolder. They resolve per machine, so a
teammate who clones the repo needs no reconfiguration.

## 5. Decide the sync mode — the one irreversible choice

You can skip this step and get the default, but read it first, because the
choice is **fixed for that sync folder** once you export. Changing your mind
later means a new empty folder and a fresh export.

- **XML-first (the default, nothing to do)** — native XML in `project-view/` is
  the canonical format, with readable `.st`/`.csv` generated beside it. Choose
  this when Git should show and control the whole project: devices, tasks,
  visualizations, not only code.
- **Text-first (opt-in in `Project_options.py`)** — `.st` files are the source of
  truth and structural XML moves into the tool-owned `.dump/xml/` mirror. Choose
  this if your reason for installing the tool is code review, external editors
  or LLM agents working on Structured Text.

Full comparison: [Sync modes](sync-modes.md).

## 6. First export

Run **`Project_export.py`**. All supported `.st` and `.csv` text exports are on
by default.

![Export Changes](../img/Export.gif)

You now have the sync folder populated. Two parts of it matter:

- `project-view/` — what you edit and what Git tracks.
- `.dump/` — tool-owned state, including the manifest that records what is
  synchronized. Generated, not hand-edited.

The full map, and what to put in `.gitignore` and Git LFS:
[Project layout](project-layout.md).

## 7. Edit, compare, import

Edit files in `project-view/` with any editor. Before importing, run
**`Project_compare_ui.py`** to see IDE versus disk, then **`Project_import.py`**
to apply disk changes back into CODESYS.

![Compare and Interactive Sync](../img/Compare-Import.gif)

A pre-import backup is taken by default. Use the normal CODESYS Undo command for
anything you want to reverse in the IDE.

Commit the change in Git. That is the whole cycle — everything below is
optional.

---

## Where to go next

Pick what matches the reason you installed the tool.

- **Find problems in the code** — `cts analyze --workspace <sync-folder>` offline,
  or **`Project_analyze_ui.py`** for the desktop findings view with previewed
  autofixes. One verdict for CI: `cts verify`.
  See [Static analyzer](../products/cds-static-analyzer/README.md).
- **Read an unfamiliar state machine** — **`Project_fsm.py`**, or `cts fsm ui`.
- **Tidy one untidy block** — **`Project_fmt.py`**, with a before/after preview.
- **Let an LLM agent drive the project** — start **`Project_daemon.py`**, then
  work through the `cts` CLI: `cts status`, `cts export`, `cts compare`,
  `cts import`, `cts build`. Give the agent symbol documentation with
  `cts docs`. See the [CLI reference](../products/cds-text-sync/src/cds_text_sync/CLI.md).
- **Draw HMI screens as text** — [HMI screens from SVG](visu.md).
- **Work in a team** — [Team workflow](workflow.md).
