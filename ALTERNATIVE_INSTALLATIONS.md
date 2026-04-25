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

### 1. Default (Recommended)
`%LOCALAPPDATA%\CODESYS\ScriptDir\`
Portable, avoids Program Files permission issues, and works with side-by-side installations.

### 2. Per-Installation
`C:\Program Files\CODESYS 3.5.x.x\CODESYS\ScriptDir\`
Ties scripts to a specific version. May require administrator rights.

### 3. Vendor Forks (DIAStudio, KeStudio, etc.)
Vendors often rebrand the path while keeping the `CODESYS\ScriptDir` structure.
Example: `...DIAStudio\DIADesigner-AX 1.9\CODESYS\ScriptDir\`

> [!TIP]
> Use **Option 2** in the [Quick Installer](irm/setup.md) to provide a custom path. You can quickly get the path by holding **Shift + Right-click** on the folder in File Explorer and choosing **Copy as path**.

## Common Pitfalls & Troubleshooting

- **ScriptDir missing:** Create it manually before installation or let the Quick Installer create it.
- **Scripts not in menu:**
  1. Ensure files are in `ScriptDir\cds-text-sync`.
  2. Restart CODESYS completely.
  3. Verify `.py` and `.pyw` files are both present (don't copy only `.py`).
- **Python errors:** `cds-text-sync` uses the internal CODESYS Python environment. Don't worry about your system's global Python version unless the vendor fork uses a vastly different API.

## Validation Checklist

1. Restart the engineering tool.
2. Confirm scripts appear under `Tools -> Scripting`.
3. Run `Project_directory.py` to set a sync folder.
4. Run `Project_export.py` on a test project.

## How to Report a New Environment

If you successfully install on a new fork, please open an issue with:
- Product name / Version
- ScriptDir path used
- Confirmation of menu appearance and basic export/import functionality.

## Summary

- Use the [Quick Installer](irm/setup.md) if possible.
- Choose **Option 2** for alternative paths.
- Point to the specific product's `CODESYS\ScriptDir`.
- Restart and test with a small export.
