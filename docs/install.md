# Installation

## Requirements

- **CODESYS**: V3.5 SP16 or newer. Tested on SP16 Patch 9
  (x86) and SP22 (x64); older versions are not tested.
- **Windows 10 or 11**: `cts.exe` and the in-IDE agent are .NET Framework 4.8
  programs, which Windows 10 1903 and later include.
- **Git Required**: the sync folder is a Git repository; setting it (Alt+Q, `8`,
  `1`, or `cts set-sync-folder`) runs `git init` there, and branches, commits and the sync base are Git's. The
  quick installer checks for `git` and can install it with `winget`. A team's
  repository keeps the project file in Git LFS, which Git for Windows includes.

---

## How the install is laid out

Two folders, and it is worth knowing which is which:

- **Program folder** — the tool itself. Default `%LOCALAPPDATA%\cds-text-sync\`,
  or any folder you choose, including a Git clone.
- **ScriptDir** — the CODESYS scripting folder. It receives **only the
  `cds-text-sync` folder**: the menu entry `cds-text-sync.py` and, in its
  `agent` folder, the in-IDE agent with a copy of `cts.exe`.
- **Script Commands** — the sibling folder CODESYS uses for toolbar commands.
  The installer puts `cds-text-sync.py`, its icon and `config.json` entry there.

The split is not cosmetic. CODESYS scans its ScriptDir recursively and lists
every `.py` it finds, so installing the whole tool there would put the
program's own scripts into **Tools > Scripting** alongside the `cds-text-sync`
entry you actually use.
Keeping the program out of ScriptDir is what keeps that menu clean.

Run `cts install --check` at any time to see whether the menu and the agent are up to date.

---

## Method 1: Quick PowerShell Setup (Recommended)

Automate everything — download, both folders, CLI, menu — with one command:

```powershell
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

> [!NOTE]
> - **Downloads zip archives**: the tool comes as a clean zip from GitHub, not
>   a clone with history. Git is still needed for the sync folder itself.
> - **Choose version**: the interactive menu offers the latest `main`, a stable
>   release, or a test / pre-release build. A branch shared for testing is
>   installed by name instead (`CTS_BRANCH`, see the
>   [Quick Setup Guide](../irm/setup.md#a-test-branch)).
> - **Prints a map**: The installer ends by printing the program folder, the
>   menu folder, and the CLI command, so you never have to guess where things
>   went.
> - **Migrates older installs**: If a previous version sits inside ScriptDir,
>   the installer moves it out and writes the menu entry in its place.
>   Your own files in it (`projects.json`) are carried across.

> [!TIP]
> For a detailed explanation of what the script does, check the
> [Quick Setup Guide](../irm/setup.md).

---

## Method 2: Manual Copy

Extract the archive **anywhere except a CODESYS ScriptDir** — for example
`%LOCALAPPDATA%\cds-text-sync\` — then run the bundled CLI from that folder:

```powershell
products\codesys-agent\dist\cts.exe install --toolbar
```

To use `cts` from any terminal, add `<program-folder>\products\codesys-agent\dist` to the user PATH:

```powershell
[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";<program-folder>\products\codesys-agent\dist", "User")
```

`cts install` writes the menu entry into the first CODESYS ScriptDir it finds,
with the in-IDE agent and `cts.exe` beside it, taken from beside the `cts.exe`
that runs it: the prebuilt files in `products/codesys-agent/dist` (kept in Git
LFS; the quick installer fetches them when the zip holds only their LFS
pointers, and a clone needs `git lfs pull`), or in a build tree the agent built
with that `cts.exe`. Once that folder is on PATH, `cts install` does the same.
CODESYS must be closed while the agent changes.

`cts install` also cleans up after an older install in the same ScriptDir:
generated stubs under other names, in the menu folder or in `<ScriptDir>`
itself, and Python caches. It removes only files it recognises as its own
(stubs by their generated marker, and the `Project_compare.py`,
`Project_parameters.py` and `Project_perf_test.py` scripts releases before 3.0
wrote whole), reports each one, names anything else it
leaves in place, and `--check` shows the same list without changing anything.

These are the ScriptDir locations it knows about:

- **Standard (User Profile)**: `C:\Users\<YourUsername>\AppData\Local\CODESYS\ScriptDir\`
- **Legacy CODESYS (< ~3.5.17)**: `C:\ProgramData\CODESYS\ScriptDir\` — older
  CODESYS (e.g. 3.5.16) scans this machine-wide path, **not** the user profile
  one. May require administrator rights.
- **Standard CODESYS (Manual Setup)**: `C:\Program Files\CODESYS 3.5.18.40\CODESYS\ScriptDir\`
- **Delta Industrial Automation (DIAStudio)**: `C:\Program Files\Delta Industrial Automation\DIAStudio\DIADesigner-AX 1.9\CODESYS\ScriptDir`

Without options `cts install` updates every ScriptDir that already holds
cds-text-sync (an IDE may load the agent from any of them), or the first one
found when none does; `--check` looks at the same ones, files a running
CODESYS holds included. Pass `--script-dir <path>` to target one explicitly,
or `--all` to serve every CODESYS installation from a single program folder.
When the IDE runs an agent of another build, every command names the
ScriptDir it came from.

> [!TIP]
> Using a different CODESYS version or fork? See the
> [Alternative Installations Guide](alternative-installations.md) for supported
> environments and installation paths.

---

## Method 3: Git clone

For updates through `git pull`, and for development. Clone **anywhere except a
ScriptDir**:

```powershell
git clone https://github.com/ArthurkaX/cds-text-sync C:\Tools\cds-text-sync
cd C:\Tools\cds-text-sync
git lfs pull
products\codesys-agent\dist\cts.exe install --toolbar
```

Nothing has to be deleted from the clone, and nothing is copied into ScriptDir
except the menu entry and the agent. Updating afterwards is:

```powershell
git pull
cts install
```

`cts install --check` reports when the installed agent and the clone have
drifted apart.

---

## Use the CLI

The bundled CLI is `products\codesys-agent\dist\cts.exe`. Add its folder to the user PATH to use `cts` from any terminal, as shown in the manual installation steps above.

## After installing

1. **Access in CODESYS**: the entry appears under
   **Tools > Scripting > Scripts > C > cds-text-sync**, and nothing else from this tool appears
   anywhere else in that menu.
2. **Toolbar button**: the `cds-text-sync` button
   (<img src="../img/cts-button.png" alt="CTS two-arrow button" height="20">) starts the agent
   and opens the quick window, just like **Tools > Scripting > Scripts > C >
   cds-text-sync**. Setup adds it to the Standard toolbar when CODESYS is
   closed. If CODESYS was open, close it and run `cts install --toolbar`.
   To add it yourself, use **Tools > Customize > Toolbars > Add Command >
   ScriptEngine Commands > cds-text-sync**.

   The toolbar button is a shortcut to the same menu entry.

3. **Link a project to disk**: open the project in CODESYS and run
   `cds-text-sync.py` to start the in-IDE agent. Press Alt+Q, then `8` and `1`,
   and take the suggested folder: the root of the git repository the `.project` lies in, else
   `<project>-cts` beside it (or `cts set-sync-folder`); the folder becomes a git repository right away.
   On a project someone else set up, clone its repository first; Alt+Q then opens on this row and
   asks for the clone.
   Then press `2` in the quick window, or run `cts export`. All supported `.st` and `.csv` text exports are enabled
   by default; use the quick window's Settings page for changes. See
   [Script overview](scripts.md) and
   [Recommended workflow](../readMe.md#2-git-workflows).

---

## Upgrading from previous versions

1. **Check stable releases**: first check whether there is a newer stable release
   at [GitHub Releases](https://github.com/ArthurkaX/cds-text-sync/releases).
2. **Close CODESYS and re-run the installer**, or replace the contents of the
   program folder and run `cts install` again. CODESYS holds the agent while it
   runs: `cts install` names a CODESYS that holds it instead of writing half an
   install, and `cts install --check` says whether anything is out of date.
3. **Coming from cds-text-sync 3.x**: the old sync folder is not taken over
   (`cts set-sync-folder` refuses a folder with `.dump/manifest.json`). Choose
   a new folder with `cts set-sync-folder`, then `cts export` and `cts commit`.

> **Upgrading from a version installed inside ScriptDir**: older releases put the
> whole tool in ScriptDir. Those installs keep working untouched, so there is no
> rush — but the IDE menu stays cluttered until you migrate. Re-running the
> quick installer does the move for you. Doing it by hand is the same two steps
> as a fresh install: move the folder out of ScriptDir, then run
> `cts install` from its new location. Toolbar buttons survive either way,
> because the menu entry keeps its name.
>
> **Rollback**: If you encounter issues with a new version, see
> [Releases & rollback](releases.md) for how to safely revert to a previous
> stable version.
