# Upgrading to 4.0 (beta)

4.0 is a new cds-text-sync: `cts.exe` and an agent DLL running inside CODESYS replace the Python package and the `Project_*.py` scripts. It is a beta: it is tested on the versions listed under [Known limits](#known-limits), and the last 3.x release, 3.4.1, stays one menu choice away. `cts --version` prints the version and the build commit; please include both in reports.

## Install, update and go back

Close CODESYS, then run in PowerShell:

```powershell
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

Enter (`L`, the `main` branch) installs the beta; running the same line again updates it. The `T` entries of the menu are the tagged beta builds, for staying on one of them.

To go back to 3.4.1, run the same line and pick `1` (3.4.1). A release up to 3.4.1 has its own installer: this one takes the agent out of the menu folder, starts that installer, and you pick 3.4.1 again in its menu. The sync folder each project remembers (`projects.json`) is kept for a later update. Running the 3.4.1 installer directly instead leaves the 4.0 `agent` folder in the menu folder, reports it as a problem, and forgets `projects.json`.

A build handed over as a `*-setup.zip` installs without GitHub: unzip it and run `install.cmd`.

## What changes on upgrade

- A 3.x sync folder is not taken over: start in a new folder. Open the project, run `cts set-sync-folder PATH` with a new folder (it refuses one with `.dump/manifest.json`), then `cts export` and `cts commit`.
- Git is required; each sync folder is a git repository and commands use its history and sync base.
- The CODESYS menu has one `cds-text-sync` entry, and the installer puts its button on the Standard toolbar. The old `Project_*.py` scripts stay where 3.x put them: the installer deletes nothing of yours in ScriptDir, it names each one it finds (`note: an older release's script ...; delete it: PATH`). They are still listed under Tools > Scripting but no longer work; delete them.
- The old Python `cts` package is replaced by `cts.exe`. The installer offers to remove the old pip command if it takes precedence.
- `cts visu-lint` is replaced by `cts visu check --screen NAME`. `cts install-menu` and `cts where` are replaced by `cts install`.
- The former `cts ui`, `cts config ui`, `cts daemon start|stop`, `cts snapshot`, and `cts last-result` commands are removed. Use the quick window, `cts status`, and `cts read-log` where applicable.
- Analysis settings now live in the `analyze` section of `cds-text-sync.json`; suppressions are in `.cts-analyze/suppressions.json`.
- `cts docs --output DIR` is now `cts docs --out DIR`; `cts analyze --format sarif` is now `cts analyze --sarif FILE`. `cts verify --probe-timeout` is removed.
- `cts merge --merge-tool` and `cts project update --merge-tool` are removed: branches, and a pull that meets the same lines changed on both sides, are merged in your git program (`cts open` opens the sync folder in it).
- Whole-project import options `--whole` and `--no-refresh` are removed. `cts fsm` replaces `fsm ide|scan|show`; SVG and PlantUML FSM renderings are removed.

## What is new

- The toolbar button or the menu entry starts the in-IDE agent and opens the quick window; Alt+Q opens it afterwards.
- `cts set-sync-folder` works on a brand-new project. The sync folder is a git repository; `cts status` reports its branch, commit, and uncommitted changes.
- `cts export` writes a POU or interface, including its methods, properties, actions, and accessors, as one `.st` file. `cts sync` carries non-overlapping edits in both directions, labels each change `disk -> IDE` or `IDE -> disk` (`merged` for a merge), and `cts import --dry-run` previews changes and conflicts.
- Compare reports IDE and disk changes separately. Branch and commit workflows are available in the quick window and CLI.
- A colleague can leave the task configuration, the alarms or a device to the project's owner: list them in the clone's `.git/info/exclude` (`**/Task Configuration/`), and export, import and compare leave those files as they are ([Working as a team](team.md#parts-only-the-owner-changes)).
- `cts analyze` and `cts fsm` run inside `cts.exe`: a large project is analyzed in seconds, with far fewer false findings. `cts fmt` lays out the IDE's ST (indentation in editor columns, aligned declarations), or with `--disk` the sync folder's files, and changes it only with `--write`; `cts new` writes a new POU, GVL, DUT or member as a `.st` file for `cts import`.
- If a command is stopped by an open IDE dialog, it exits with code 3 and prints the ready `cts dialog answer ...` command.

## Known limits

- Tested on CODESYS V3.5 SP22 (x64), and V3.5 SP16 Patch 9 (x86).
- A project saved by a newer CODESYS may open in an older one with objects marked `[incomplete]`. Then `cts export` and `cts compare` refuse to run and write nothing. Use a project saved in the oldest CODESYS version that will open it.
- On a machine with both SP16 and SP22, check that the menu appears in both CODESYS versions. SP16 uses the legacy machine-wide ScriptDir; newer versions use the user ScriptDir.

## Reporting a problem

Include:

- The exact command line and its full output, including errors, `[WARN]` and `[INFO]` lines.
- The output of `cts --version` (including its commit), `cts agent list` (the agent's build) and `cts status`.
- The agent log at `%TEMP%\cts-agent.log`.
