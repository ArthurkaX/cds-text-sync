# Alternative Installations Guide

This guide explains how to install `cds-text-sync` in non-standard environments (vendor forks, older/newer CODESYS versions, or custom paths).

## Support Status

| Level | Meaning |
| --- | --- |
| **Recommended** | Standard CODESYS V3.5 SP13+ (ScriptDir layout) |
| **Community** | Reported compatible, but not fully regression-tested |
| **Experimental** | Future versions or heavily customized vendor forks |

**Recommended Baseline:**
- **CODESYS:** V3.5 SP10+ (SP13+ preferred)
- **OS:** Windows
- **Feature:** Must have `Tools -> Scripting`

## Installation Paths

> [!IMPORTANT]
> **CODESYS version matters.** Newer CODESYS scans the per-user `%LOCALAPPDATA%\CODESYS\ScriptDir`, while **older CODESYS (roughly before V3.5 SP17, e.g. 3.5.16) only scans the machine-wide `%PROGRAMDATA%\CODESYS\ScriptDir`**. If you install into `%LOCALAPPDATA%` on an old CODESYS, the scripts will **not** appear under `Tools -> Scripting`. The [Quick Installer](../irm/setup.md) auto-detects the installed version and recommends the correct path; on a legacy install pick option **[3] Legacy CODESYS**.

### 1. Default (Recommended, modern CODESYS)
`%LOCALAPPDATA%\CODESYS\ScriptDir\`
Portable, avoids Program Files permission issues, and works with side-by-side installations.

### 1b. Legacy CODESYS (< 3.5.17)
`%PROGRAMDATA%\CODESYS\ScriptDir\`
Machine-wide path scanned by older CODESYS. Writing here usually requires **administrator rights** — run the installer (or the copy step) from an elevated PowerShell.

### 2. Per-Installation
`C:\Program Files\CODESYS 3.5.x.x\CODESYS\ScriptDir\`
Ties scripts to a specific version. May require administrator rights.

### 3. Vendor Forks (DIAStudio, KeStudio, etc.)
Vendors often rebrand the path while keeping the `CODESYS\ScriptDir` structure.
Example: `...DIAStudio\DIADesigner-AX 1.9\CODESYS\ScriptDir\`

> [!TIP]
> Use **Option 2** in the [Quick Installer](../irm/setup.md) to provide a custom path. You can quickly get the path by holding **Shift + Right-click** on the folder in File Explorer and choosing **Copy as path**.

## Common Pitfalls & Troubleshooting

- **ScriptDir missing:** Create it manually before installation or let the Quick Installer create it.
- **Scripts not in menu:**
  1. Ensure the generated `Project_*.py` scripts are in `ScriptDir\cds-text-sync`. Run `cts install-menu` (or `python -m cds_text_sync.install_menu` from the program folder) if the folder is empty or missing.
  2. **Check the ScriptDir location matches your CODESYS version.** Old CODESYS (< ~3.5.17) reads `%PROGRAMDATA%\CODESYS\ScriptDir`, not `%LOCALAPPDATA%`. If you are on 3.5.16 or similar and generated the menu into `%LOCALAPPDATA%`, re-run with `--script-dir "%PROGRAMDATA%\CODESYS\ScriptDir"` (elevated shell), or re-run the installer and choose **[3] Legacy CODESYS**.
  3. Restart CODESYS completely.
  4. Run `cts where` — it prints the program folder, every ScriptDir it found, and any problem with the generated scripts.
- **Too much in the menu:** if internal modules such as `preview.py` or `__init__.py` show up next to the `Project_*` commands, the program folder itself is inside a ScriptDir. CODESYS scans that folder recursively. Move the program folder out of ScriptDir and run `cts install-menu` again; the generator refuses to run otherwise and names the offending path.
- **CLI command missing:** a manual installation does not install the system CLI. Run `python -m pip install -e "<program-folder>"` so `cds-text-sync --help` works from CMD, PowerShell, Git Bash, or WSL.
- **Python errors inside CODESYS scripts:** CODESYS uses its own internal Python/IronPython environment for `Project_*.py` scripts.
- **Python errors from `cds-text-sync` CLI:** the system CLI uses your Windows Python 3 installation.

## Validation Checklist

1. Restart the engineering tool.
2. Confirm the `Project_*` commands appear under `Tools -> Scripting`, and that nothing else from this tool does.
3. Run `python -m pip install -e "<program-folder>"` if the installer did not install the CLI.
4. Confirm `cds-text-sync --help` works in a new shell.
5. Run `cts where` and check that the program folder and the menu folder are the ones you expect.
6. Run `Project_directory.py` to set a sync folder.
7. Run `Project_export.py` on a test project.

## How to Report a New Environment

If you successfully install on a new fork, please open an issue with:
- Product name / Version
- ScriptDir path used
- Confirmation of menu appearance and basic export/import functionality.

## Summary

- Use the [Quick Installer](../irm/setup.md) if possible.
- Choose **Option 2** for alternative paths.
- Point to the specific product's `CODESYS\ScriptDir` — only the generated `Project_*.py` scripts go there; the tool itself lives outside it.
- Install the system CLI separately with `python -m pip install -e "<program-folder>"` if needed.
- Restart and test with a small export.
