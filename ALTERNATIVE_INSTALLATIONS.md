# Alternative Installations Guide

This guide explains how to install `cds-text-sync` when you are not using the default user-profile ScriptDir path, or when you are working with a CODESYS fork or an older/newer engineering package.

It is based on:

- the current quick installer flow in [`irm/setup.ps1`](irm/setup.ps1)
- the setup notes in [`irm/setup.md`](irm/setup.md)
- real user reports from closed GitHub issues

The goal is to help you install the tool safely without overstating official compatibility.

## Support Status

`cds-text-sync` is a third-party tool and is not officially supported by CODESYS Group or by vendors shipping CODESYS-based products.

At the moment, support should be understood in three levels:

| Level | Meaning |
| --- | --- |
| Recommended | Standard CODESYS installations that use the normal scripting system and ScriptDir layout |
| Community-reported | Environments reported by users as installable or likely compatible, but not fully regression-tested in this repository |
| Experimental | Future or vendor-specific environments that may work, but need validation on a real project |

## Recommended Baseline

These are the current baseline expectations for the project:

- Minimum recommended family: `CODESYS V3.5 SP10+`
- Best experience: `CODESYS V3.5 SP13+`
- Operating system: Windows
- Script engine access required: `Tools -> Scripting`

If your environment is much older, heavily customized, or vendor-locked, install may still succeed, but behavior should be treated as experimental until verified on a test project.

## Installation Paths

### 1. Standard User Profile Path

This is the safest and most portable option:

```text
C:\Users\<YourUserName>\AppData\Local\CODESYS\ScriptDir\
```

This is the default path used by the quick installer.

Why this is recommended:

- does not depend on a specific CODESYS installation folder
- avoids permission issues under `Program Files`
- works well with updates and side-by-side testing

### 2. Standard CODESYS Program Files Path

Some users prefer a per-installation setup:

```text
C:\Program Files\CODESYS 3.5.x.x\CODESYS\ScriptDir\
```

Use this when:

- you want the scripts tied to one exact engineering installation
- your organization manages tooling per installed version

Be aware:

- you may need administrator rights
- some systems do not create `ScriptDir` automatically
- updates to the engineering package may overwrite or reset local files

### 3. Vendor Fork / Rebranded CODESYS Path

Some vendors ship CODESYS under their own product names. In those cases, the correct target is still the product's `ScriptDir` folder.

Community examples include:

- DIA Designer / DIAStudio
- KeStudio
- other vendor-specific CODESYS distributions

Example:

```text
C:\Program Files\Delta Industrial Automation\DIAStudio\DIADesigner-AX 1.9\CODESYS\ScriptDir\
```

If you are unsure where the folder is:

1. Open File Explorer
2. Navigate to your engineering installation
3. Find the `CODESYS\ScriptDir` folder
4. Hold `Shift`, right-click the folder, and choose `Copy as path`

This is the same flow the quick installer expects when you choose the alternative path option.

## Quick Installer Behavior

The quick installer:

```powershell
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

supports two installation modes:

- `Option 1`: default user-profile ScriptDir
- `Option 2`: manually entered alternative ScriptDir path

When `Option 2` is used, the installer:

- asks for the full ScriptDir path
- strips surrounding quotes if needed
- creates the directory if it does not exist
- installs `cds-text-sync` inside that ScriptDir

This makes it suitable for most vendor forks, as long as their scripting engine behaves like standard CODESYS.

## Community-Reported Environments

The following environments have been mentioned by users and are useful reference points:

### Standard CODESYS SP18 / SP19 / SP21

User reports indicate that multiple 3.5 service packs are actively used with the tool, including:

- SP18
- SP19
- SP21

In practice, these versions are good candidates for normal use, but behavior can still differ depending on patch level and installed packages.

### DIA Designer / DIAStudio

This environment has already been referenced in the repository documentation and installer flow as a real target path.

Expected status:

- installation: likely supported
- scripting integration: depends on that product's CODESYS packaging
- full validation: still best done on a reference project before production rollout

### Other Forks

Closed issue discussions suggest that some users can install the scripts into forked environments even when menu behavior differs.

That usually means one of two things:

- the ScriptDir path is valid, but the product exposes scripts differently
- the fork restricts or changes part of the standard CODESYS scripting UI

If the files are present but scripts do not appear in the menu, treat that as a product-specific integration problem rather than immediate proof that `cds-text-sync` itself is incompatible.

## Known Installation Pitfalls

### `ScriptDir` does not exist

This is normal on some systems.

Fix:

- create the folder manually
- then copy the project files there or rerun the installer

Expected folder examples:

```text
C:\Users\<YourUserName>\AppData\Local\CODESYS\ScriptDir\
```

or

```text
C:\Program Files\<Vendor Product>\CODESYS\ScriptDir\
```

### Scripts do not appear in the menu

Possible causes:

- the wrong ScriptDir was used
- the engineering package exposes scripting differently
- the application needs a restart after file copy
- the fork supports scripting, but not the same menu layout as standard CODESYS

Recommended checks:

1. Confirm the files are inside the correct `ScriptDir\cds-text-sync` folder
2. Restart the engineering environment completely
3. Check `Tools -> Scripting`
4. Verify that `Project_*.py` files are present
5. Verify that `.pyw` helper modules were copied too

### Only copying `.py` files

Do not copy only the visible scripts.

You must copy:

- all `Project_*.py` files
- all `codesys_*.pyw` files

The `.pyw` files are intentionally hidden from the scripts menu, but they are required at runtime.

### Python version confusion

Some users assume they must separately install or manage a desktop Python runtime for the tool.

In most cases, that is not the actual requirement.

`cds-text-sync` is designed for the CODESYS scripting environment. If a forked product behaves differently, the important question is not "Which Python version is installed globally?" but:

- does the engineering environment expose a compatible scripting API?
- does it load the scripts from the correct ScriptDir?

If you see import errors inside a vendor environment, first validate file placement and packaging before blaming the system Python installation.

## Validation Checklist After Installation

After installing, verify the setup with this sequence:

1. Restart the engineering tool
2. Confirm the scripts appear under `Tools -> Scripting`
3. Run `Project_directory.py`
4. Set a test sync folder
5. Run `Project_export.py` on a small project
6. Check that `.st` files are written successfully
7. Optionally enable XML export and verify `.xml` output for supported native objects

If this succeeds, your environment is very likely usable for normal development.

## Best Practices for Forks and Mixed Environments

- Prefer the user-profile ScriptDir when possible
- Test on a small non-critical project first
- Keep one known stable tagged release available for rollback
- After upgrades, restart the engineering tool before judging whether the new version loaded correctly
- If your team uses different vendor packages, document the exact installation path per product

## How to Report a New Environment

If you want to help improve compatibility documentation, include the following in your issue or discussion:

- product name
- exact version and patch level
- whether it is stock CODESYS or a vendor fork
- the ScriptDir path you used
- whether scripts appeared in the menu
- whether `Project_directory.py`, `Project_export.py`, and `Project_import.py` worked
- any screenshots or error messages

That makes it much easier to move an environment from "community-reported" toward "recommended."

## Practical Summary

If you are unsure which path to choose:

- use the quick installer for normal CODESYS installations
- choose the alternative path option for forks like DIAStudio or KeStudio
- point it to the product's real `CODESYS\ScriptDir`
- restart the engineering environment and validate with a small export

If you discover a fork-specific quirk, the tool may still be usable. In most cases, the right next step is documentation or a small compatibility fix, not a full redesign.
