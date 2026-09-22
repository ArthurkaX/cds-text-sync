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

Reading it out of order costs nothing anyway: a command that needs a sync folder
and finds none offers the setup dialog on the spot and then carries on, so
whichever command you reach first can configure the project.

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
saves it in the project properties. Any other command that needs a folder and
finds none asks the same question, so you may have answered it already.

![Setup Project Directory](../img/setFolder.gif)

The suggested answer is a folder named after your project — `MyProject-cts` —
beside the `.project` file, and pressing Enter takes it. The name is stored
relative, so it resolves per machine and a teammate who clones the repository
needs no reconfiguration. `.` uses the project directory itself; **Browse…**
picks any folder, and one inside the project is stored relative too. Nothing is
created on disk until the first command actually writes there.

## 5. Decide the sync mode — the one irreversible choice

`Project_directory.py` opens the options dialog straight after a folder is
configured for the first time, so this choice is usually in front of you already.
Read it before clicking through, because the choice is **fixed for that sync
folder** once you export. Changing your mind later means a new empty folder and a
fresh export. Cancelling the dialog keeps the folder and leaves the defaults.

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
