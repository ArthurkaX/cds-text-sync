# Alternative Installations Guide

This guide explains how to install `cts` and its CODESYS menu entry in non-standard environments (vendor forks, older/newer CODESYS versions, or custom paths).

## Support Status

| Level | Meaning |
| --- | --- |
| **Tested** | CODESYS V3.5 SP16 Patch 9 (x86), SP22 (x64) |
| **Community** | Reported compatible, but not fully regression-tested |
| **Experimental** | Future versions or heavily customized vendor forks |

**Baseline:**
- **CODESYS:** V3.5 SP16 or newer, or a fork built on it
- **OS:** Windows 10 or 11 (.NET Framework 4.8)
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
  1. Ensure the menu entry is in `ScriptDir\cds-text-sync`. Run `products\codesys-agent\dist\cts.exe install --toolbar` from the program folder if the folder is empty or missing.
  2. **Check the ScriptDir location matches your CODESYS version.** Old CODESYS (< ~3.5.17) reads `%PROGRAMDATA%\CODESYS\ScriptDir`, not `%LOCALAPPDATA%`. If you are on 3.5.16 or similar and generated the menu into `%LOCALAPPDATA%`, re-run with `--script-dir "%PROGRAMDATA%\CODESYS\ScriptDir"` (elevated shell), or re-run the installer and choose **[3] Legacy CODESYS**.
  3. Restart CODESYS completely.
  4. Run `cts install --check` — it names the menu folder it found and anything out of date or in the way.
- **Too much in the menu:** if other `.py` files of the tool show up next to the `cds-text-sync` entry, the program folder itself is inside a ScriptDir. CODESYS scans that folder recursively. Move the program folder out of ScriptDir and run `cts install` again.
- **CLI command missing:** add `<program-folder>\products\codesys-agent\dist` to the user PATH to run `cts` from new terminals. In PowerShell, run `[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";<program-folder>\products\codesys-agent\dist", "User")`.
- **Errors inside CODESYS:** the `cds-text-sync.py` menu entry runs in CODESYS's own IronPython and only loads the in-IDE agent (.NET); a box saying the agent did not start names the cause, and `cts install` puts the agent back.


## Validation Checklist

1. Restart the engineering tool.
2. Confirm the `cds-text-sync` menu entry appears under `Tools -> Scripting`, and that nothing else from this tool does.
3. Add `<program-folder>\products\codesys-agent\dist` to the user PATH.
4. Confirm `cts --help` works in a new shell.
5. Run `cts install --check` and check that the menu folder is the one you expect and nothing is out of date.
6. Run the CODESYS menu entry on a test project, then set its sync folder with
   `cts set-sync-folder` (or Alt+Q, `8`, `1`).
7. Run `cts export`.

## How to Report a New Environment

If you successfully install on a new fork, please open an issue with:
- Product name / Version
- ScriptDir path used
- Confirmation of menu appearance and basic export/import functionality.

## Summary

- Use the [Quick Installer](../irm/setup.md) if possible.
- Choose **Option 2** for alternative paths.
- Point to the specific product's `CODESYS\ScriptDir` — only the generated menu stub goes there; the tool itself lives outside it.
- Add the bundled CLI folder to the user PATH if needed.
- Restart and test with a small export.
