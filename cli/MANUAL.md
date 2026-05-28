# MANUAL.md — cds-text-sync: LLM Agent Guide

This document tells LLM agents (and humans) how to use `cds-text-sync` (v2.5.1)
to control CODESYS PLC IDE. Designed for reliable, repeatable automation.

## Quick Start

First, a human must:
1. Open the CODESYS project in the IDE
2. Run `Project_daemon.py` via Tools → Scripting → Execute Script
3. The daemon starts polling (startup messages in dashboard, only errors shown as notifications)

Then the agent can talk to CODESYS:

### Shell Compatibility
- **Manual/system CLI install is required:** copying files into CODESYS `ScriptDir` does not put `cds-text-sync` in `PATH`.
- **After `python -m pip install -e .` (recommended):** `cds-text-sync rp ping --timeout 10`
  works in any shell (CMD, PowerShell, Git Bash, WSL) because pip creates a `.exe` in Python `Scripts/`.
- **Windows CMD:** `cds-text-sync rp ping --timeout 10` (console script created by pip, if Python `Scripts/` is in `PATH`)
- **Git Bash (MSYS):** `python cli/cds_text_sync.py rp ping --timeout 10`
  (use the direct Python form if MSYS path translation interferes with the installed console script)
- **WSL:** `python.exe cli/cds_text_sync.py rp ping --timeout 10`
  (use `python.exe`, the Windows Python, not Linux Python)
- **PowerShell:** `cds-text-sync rp ping --timeout 10` or `python cli/cds_text_sync.py rp ping --timeout 10`

```bash
# Universal after python -m pip install -e .
cds-text-sync rp ping --timeout 10
```

```bash
# Check daemon is alive
cds-text-sync rp ping --timeout 10
# → {"status": "pong", "pid": 1234}

# Get detailed daemon/project status
cds-text-sync rp status --timeout 10
# → {"running": true, "pid": 1234, "sync_folder": "C:/path/..."}

# Connect to a PLC
cds-text-sync rp connect_to_device --ip 192.0.2.10 --timeout 60
# ⚠ May require human to approve dialog in CODESYS within ~2 minutes
```

## Important Rules

### 1. Always set explicit --timeout
Every `rp` command should set `--timeout`. The CLI has a small default timeout, but it is only suitable for short checks.
- `ping`, `status`, `application_state`, `sync` — 5–10s
- `read_variable`, `write_variable` — 15–25s
- `connect_to_device`, `start_plc`, `stop_plc` — 25–60s
- `build`, `source_download`, `sync_export` — 60–120s

### 2. stdout is JSON, stderr is for humans
- stdout: pure JSON, machine-readable
- stderr: `[ERROR]`, `[INFO]`, `[OK]` messages for human operators
- `--output text` / `-p` changes stdout to human-readable format
- `--manual` prints this document and exits

### 3. Connect before read/write
- `read_variable` and `write_variable` work **only after** `connect_to_device`
- `connect_to_device` **without `--ip`** uses the device already configured in the project
  (the first online device in the device tree). Useful when the project has a fixed device.
- `connect_to_device --ip 192.0.2.10` overrides with a specific IP address
- Exception: if `connect_to_device` was called earlier in the same daemon session,
  auto-connect will re-login automatically
- After `disconnect_from_device`, a fresh `connect_to_device` is needed

### 4. Command Dependency Map
Not all commands need the daemon or PLC connection:

| Level | Requires | Commands |
|-------|----------|----------|
| 🟢 **CLI only** | nothing | `--help`, `--manual` |
| 🔵 **Daemon** | running daemon in CODESYS | `ping`, `status`, `stop`, `help`, `permissions`, `project_info`, `project_tree`, `explore`, `sync`, `sync_export`, `sync_import`, `sync_compare`, `sync_export_text`, `sync_import_text`, `sync_compare_text`, `build`, `export`, `read_log` |
| 🟡 **Online** | daemon + `connect_to_device` | `read_variable`, `write_variable`, `variable_tree`, `app_crc`, `app_info`, `compare`, `start_plc`, `stop_plc`, `reset_plc`, `create_boot_app`, `source_download`, `plc_files`, `plc_download`, `plc_upload`, `plc_log`, `application_state`, `device_status`, `probe` |
| 🔴 **Permissions** | daemon + allowed in Settings | `reset_plc`, `create_boot_app`, `plc_upload`, `source_download`, `write_variable`, `build`, `sync_import` (configurable) |

### 5. Some operations need PLC in specific state
| Operation | Required PLC state |
|-----------|-------------------|
| `read_variable` | logged in (run or stop) |
| `write_variable` | logged in (run or stop) |
| `variable_tree` | connected (run or stop) |
| `app_crc`, `app_info` | connected |
| `compare` | connected (reads PLC CRC, checks local) |
| `start_plc` | stopped |
| `stop_plc` | running |
| `reset_plc --kind warm` | logged in (resets, stops) |
| `reset_plc --kind cold` | logged in (resets, stops) |
| `reset_plc --kind origin --force 1` | ⚠ DANGEROUS: erases app from PLC |
| `create_boot_app` | stopped, logged in |
| `source_download` | logged in, running (slow ~30s) |
| `build` | any (no online connection needed) ⚠️ does NOT deploy to PLC — see §8 |

### 6. Permissions can block commands
The daemon has a **permission system** configured via the **Settings window** in the dashboard (WinForms).
- CLI can **read** permissions via `rp permissions` (read-only)
- Only the Settings window can **change** permissions
- When a command is blocked: `[ERROR] Forbidden by daemon settings...`
- Default deny list: `reset_plc`, `reset_plc --kind origin`, `create_boot_app`, `plc_upload`, `source_download`
- Settings window opens via the **Settings** button in the daemon dashboard (rightmost button)

**Settings window features:**
- **General tab:** Poll frequency slider (10–10000ms, default 200ms)
- **Permissions tab:** Checkboxes for each dangerous operation
- **Apply/OK** saves to `cds-daemon-config` project property (JSON)

```bash
# Check current permissions
cds-text-sync rp permissions --timeout 5
# → {"poll_ms": 200, "deny": ["reset_plc", "create_boot_app", ...]}

# If a blocked command is attempted:
cds-text-sync rp reset_plc --kind warm --timeout 10
# → [ERROR] Forbidden by daemon settings (deny list includes 'reset_plc')
```

### 7. Building
```bash
cds-text-sync rp build --timeout 120
# → {"application": "Application", "errors": 0, "warnings": 5, ...}
```
Build works on the active `Application` object (not the Project).
Returns structured JSON with all compiler messages.

⚠️ **`build` only compiles inside the CODESYS IDE. It does NOT deploy code to the PLC.**
After building, you MUST `connect_to_device` (which triggers Online Change or Download
during login) to push the new code to the controller. See the **Deploy Workflow** below.

### 8. Deploy Workflow (Edit → Import → Build → Connect → Verify)

When you edit source files in `project-view/`, the new code must go through **four steps**
before it is active on the PLC:

```
project-view/*.st  →  CODESYS IDE  →  compiled  →  PLC controller
   (edit here)      (import+build)     (build)     (connect=download)
```

```bash
# 1. Edit source files in project-view/
#    (FB_Scale.st, MAIN.st, etc.)

# 2. Push changes into the CODESYS IDE project
#    Option A: full text-sync import
 cds-text-sync rp sync_import_text --timeout 120
#    Option B: single POU update (faster, avoids import_native issues)
 cds-text-sync rp update_pou --name FB_Scale --app CI_CD_Application \
   --st_path "CODESYS_Linux_SL/PLC Logic/CI_CD_Application/FB_Scale.st" --timeout 25

# 3. Build the application in the IDE
 cds-text-sync rp build --timeout 120
#    Check that errors == 0

# 4. Login to the PLC — this triggers Online Change / Download
#    ⚠️ This step is ESSENTIAL. Without it, the PLC runs the OLD code.
 cds-text-sync rp connect_to_device --timeout 60

# 5. If the PLC was stopped, start it
 cds-text-sync rp start_plc --timeout 25

# 6. Verify the deployed code matches the build
 cds-text-sync rp compare --timeout 30
# → {"match": true, ...}

# 7. Run tests
 cds-text-sync rp cicd --timeout 120
```

**Common mistake:** running `build` + `cicd` without `connect_to_device`
means the PLC still runs the previous version of the code.
`build` compiles inside the IDE only; `connect_to_device` (login) is what
transfers the compiled application to the controller.

If `compare` returns `match: false`, the code on the PLC does not match
the build — reconnect (`disconnect_from_device` then `connect_to_device`)
and try again.

### 9. Sync folder and .dump
The CLI revolves around the **sync folder** (`cds-sync-folder` property in project).
By default exports go into `.dump/` subfolder.

```bash
# Check sync folder
cds-text-sync rp sync --timeout 10

# Export snapshot to .dump/
cds-text-sync rp sync_export --timeout 60

# Import latest .dump/ snapshot back into project
cds-text-sync rp sync_import --timeout 120

# Compare project with .dump/ snapshot
cds-text-sync rp sync_compare --timeout 60

# --- Text-based Sync (project-view/) ---
# Full cycle export: CODESYS -> IDE.xml -> project-view/
cds-text-sync rp sync_export_text --timeout 60

# Full cycle import: project-view/ -> IMPORT.xml -> CODESYS
cds-text-sync rp sync_import_text --timeout 120

# Compare project with project-view/ (generates report)
cds-text-sync rp sync_compare_text --timeout 60

# CRC compare: PLC vs project build output
cds-text-sync rp compare --timeout 30
```

### 10. CRC-based version control
`rp app_crc` reads `Application.crc` from PLC (20 bytes: 8-byte CRC + "Application\0").
You can store this CRC+timestamp to detect changes between builds/deployments.

```bash
# Get current CRC from PLC
cds-text-sync rp app_crc --timeout 20

# Compare with local build output
cds-text-sync rp compare --timeout 20
# → match: true/false, plc_crc: "...", local_crc: "..."
```

### 11. Two "compare" commands — don't confuse

| Command | What it does | Requires |
|---------|-------------|----------|
| `rp compare` | **CRC compare** — downloads `Application.crc` from PLC, compares with local build `.crc` file | online connection to PLC |
| `rp sync_compare` | **Project compare** — compares project object names against `.dump/` XML snapshot | daemon only (no PLC) |
| `rp sync_compare_text` | **project-view/ compare** — diff report between project and `project-view/` folder | daemon + engine_cli.py subprocess |

```bash
# CRC compare — is the PLC build the same as local?
cds-text-sync rp compare --timeout 30
# → {match: true/false, plc_crc: "...", local_crc: "..."}

# Project compare — what changed since last export?
cds-text-sync rp sync_compare --timeout 60
```

### 12. PLC filesystem operations
```bash
# List files in PLC root
cds-text-sync rp plc_files --path '' --timeout 10

# List files in PlcLogic/Application
cds-text-sync rp plc_files --path 'PlcLogic/Application' --timeout 10

# Download file from PLC
cds-text-sync rp plc_download --src 'PlcLogic/Application/Application.crc' --dest 'C:/Temp/app.crc' --timeout 20
```

### 13. PLC log
```bash
# Last 50 lines of PLC runtime log
cds-text-sync rp plc_log --tail 50 --timeout 20

# Save full log to file
cds-text-sync rp plc_log --output 'C:/Logs/' --timeout 30
```

### 14. Variable tree
```bash
# Full flat list
cds-text-sync rp variable_tree --flat --timeout 60

# With values (may show value_error for non-exported symbols)
cds-text-sync rp variable_tree --flat --values --timeout 120

# Filter by pattern
cds-text-sync rp variable_tree --pattern GVL --timeout 60

# Write to file (recommended for large projects)
cds-text-sync rp variable_tree --flat --output C:/Temp/vars.json --timeout 120
```

### 15. Dashboard UI (inside CODESYS)
When the daemon starts, a WinForms dashboard shows inside CODESYS:
- **Command log:** timestamps + method names
- **Stop Daemon button:** stops polling, closes window, script exits cleanly
- **Settings button:** opens Security & Settings window (poll frequency + permissions)
- **Status label:** "Running | N commands" or "Stopped..."

Layout of the bottom bar:
```
[ Running | 0 commands ... | Stop Daemon | Settings ]
```

## Invalid Expression Handling
When `read_variable` or `variable_tree --values` encounters a symbol that is not
exported to the online application (arrays, structs, unexported POU members), the
daemon now returns:
- `read_variable`: error message explaining the symbol is not exported
- `variable_tree --values`: `"value_error": "Invalid expression (not exported to online)"`
  instead of a bogus value

## Available Commands

| Command | Description | Timeout |
|---------|-------------|---------|
| **Core** | | |
| `ping` | Minimal daemon liveness check | 5s |
| `status` | Detailed daemon/project status + sync folder | 5s |
| `stop` | Stop the daemon | 5s |
| `help` | List all commands | 5s |
| **Permissions** | | |
| `permissions` | Show security config (read-only) | 5s |
| **Online** | | |
| `connect_to_device [--ip IP]` | Connect & login | 60s ⚠ dialog |
| `disconnect_from_device` | Logout | 15s |
| `application_state` | PLC state (run/stop/none) | 10s |
| `device_status` | Device info (slow on large projects) | 60s |
| **Variables** | | |
| `read_variable --name VAR` | Read PLC variable | 25s |
| `write_variable --name VAR --value VAL` | Write PLC variable | 25s |
| `variable_tree [--flat] [--pattern] [--values] [--output]` | Full variable tree | 120s |
| **Sync folder** | | |
| `sync` | Show sync folder and .dump state | 10s |
| `sync_export [--output PATH]` | Export Native XML to .dump/ | 60s |
| `sync_import [--input PATH] [--merge]` | Import .dump/ → project | 120s |
| `sync_compare [--against PATH]` | Compare project with .dump/ | 60s |
| `sync_export_text` | Export Native XML + update `project-view/` | 60s |
| `sync_import_text` | Build IMPORT.xml from `project-view/` + import | 120s |
| `sync_compare_text` | Compare project against `project-view/` | 60s |
| **Build** | | |
| `build [--output PATH]` | Build application | 120s |
| `export [--output PATH]` | Export project snapshot | 30s |
| **PLC lifecycle** | | |
| `start_plc` | Start PLC | 25s |
| `stop_plc` | Stop PLC | 25s |
| `reset_plc --kind warm\|cold\|origin` | Reset PLC | 30s |
| `create_boot_app` | Create boot app | 30s |
| **Diagnostics** | | |
| `app_crc` | CRC + metadata from PLC | 20s |
| `app_info` | App version, state, assembly info | 20s |
| `compare` | CRC comparison: IDE vs PLC | 30s |
| `probe` | Introspect OnlineApplication API | 15s |
| `explore` | Explore available APIs | 15s |
| `discover` | Discover CODESYS IDE features (needs daemon + open project) | 10s |
| `read_log [--last N] [--clear]` | IDE system messages | 10s |
| **PLC filesystem** | | |
| `plc_files [--path DIR]` | List PLC filesystem | 15s |
| `plc_download --src PATH [--dest PATH]` | Download file from PLC | 30s |
| `plc_log [--tail N] [--output DIR]` | PLC runtime log | 30s |
| **Legacy** | | |
| `source_download [--output DIR]` | Download sources | 60s |

## Error Handling

All errors follow this pattern:
```json
{"ok": false, "error": "Error message explaining what went wrong"}
```

Common errors:
- `"Reverse pipe error: Timeout..."` → daemon not running or busy. Check CODESYS.
- `"Not connected. Call connect_to_device first."` → need to connect first
- `"Invalid expression: 'X' is not exported..."` → symbol not available online
- `"DANGEROUS: reset_plc --kind origin..."` → needs `--force` flag
- `"Forbidden by daemon settings..."` → command blocked by permissions
- `"IDE process is running but NOT responding..."` → dialog in CODESYS, human intervention needed

## Smart Timeout Diagnostics

When a command times out, the system automatically checks:
1. Is the IDE process still alive? → if not, suggest restarting daemon
2. Is the IDE process responding? → if not, suggest checking for dialogs
3. CPU usage → near-zero means idle/blocked, non-zero means busy

This helps distinguish "command is slow" from "command is stuck on a dialog".

## Troubleshooting: No Output / Connection Issues

| Symptom | Likely Cause | Solution |
|---------|-------------|----------|
| `[ERROR] Reverse pipe error: Timeout...` | Daemon not running | Run `Project_daemon.py` in CODESYS (Tools → Scripting → Execute Script) |
| `[ERROR] IDE process is running but NOT responding` | Dialog open in CODESYS | Ask human to close the dialog, retry |
| `[ERROR] Forbidden by daemon settings` | Command blocked by permissions | Human unchecks it in Settings window of dashboard |
| Empty output / nothing happens | Wrong Python or path | Use `python cli/cds_text_sync.py` explicitly (see Shell Compatibility) |
| `'cds-text-sync' is not recognized` | Python `Scripts/` directory is not in `PATH`, or the editable install was not run | Run `python -m pip install -e .`, then open a new shell; or use `python cli/cds_text_sync.py` |
| daemon log shows "Sync folder not configured" | `cds-sync-folder` property not set in project | Set the project property (or run `Project_directory.py` in CODESYS) |
| `cicd` tests pass with wrong/stale results | Code not deployed to PLC after edit+build | Run `connect_to_device` after `build` to trigger download, then `compare` to verify |
| `connect_to_device` needed after code changes | `build` only compiles in IDE, doesn't push to PLC | Always follow: edit → `sync_import_text`/`update_pou` → `build` → `connect_to_device` → `start_plc` → `cicd` |
| Rising-edge FB loses trigger in CICD tests | `xExecute AND NOT xPrev` edge lost due to write timing | Use continuous execution (`IF xExecute`) or add `wait` between reset and trigger |
| `connect_to_device` hangs forever | No online device in project, or wrong IP | Check device tree in CODESYS; add a device or use `--ip` |
| Permission check shows unexpected deny list | Settings window was used to change permissions | Check `rp permissions` for current state; only Settings window modifies it |
| `sync_export` / `sync_import_text` fails with exit code 9009 | CODESYS subprocess resolved `python` to Windows Microsoft Store alias (broken) | Check `PATH`: make sure a working Python 3 install is listed *before* `C:\Users\<User>\AppData\Local\Microsoft\WindowsApps\`. Or reinstall Python from python.org to a standard location like `C:\Users\<User>\AppData\Local\Programs\Python\Python312\`. |

## Example Workflows

### Read-Modify-Write
```bash
# 1. Connect (approve dialog in CODESYS if needed)
cds-text-sync rp connect_to_device --ip 192.0.2.10 --timeout 60

# 2. Read
cds-text-sync rp read_variable --name GVL_HMI.HMI_start --timeout 25

# 3. Write
cds-text-sync rp write_variable --name GVL_HMI.HMI_start --value TRUE --timeout 25
```

### Full Sync Workflow (Export → Compare → Import)
```bash
# 1. Export current project to .dump/
cds-text-sync rp sync_export --timeout 60

# 2. Compare with latest snapshot
cds-text-sync rp sync_compare --timeout 60

# 3. (If needed) restore from snapshot
cds-text-sync rp sync_import --timeout 120
```

### Build and Check Results
```bash
# Build
RESULT=$(cds-text-sync rp build --timeout 120 2>/dev/null)

# Parse errors
ERRORS=$(echo "$RESULT" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('errors', '?'))")
if [ "$ERRORS" -gt 0 ]; then
  echo "Build failed with $ERRORS errors"
  echo "$RESULT" | python -c "import sys,json; d=json.load(sys.stdin); [print(m['text']) for m in d.get('messages',[]) if 'Error' in m.get('severity','')]"
fi
```

### PLC Lifecycle
```bash
# Stop → create boot app → reset warm → start
cds-text-sync rp stop_plc --timeout 25
cds-text-sync rp create_boot_app --timeout 25
cds-text-sync rp reset_plc --kind warm --timeout 25
cds-text-sync rp start_plc --timeout 25
cds-text-sync rp application_state --timeout 10
```

### Version Control Check
```bash
# 1. Get CRC from running PLC
cds-text-sync rp app_crc --timeout 20
# → {"crc_hex": "b11a9000...", "creation_time": "5/26/2026 10:16:17 PM"}

# 2. Compare with local build
cds-text-sync rp compare --timeout 20
# → {"match": true/false, ...}

# 3. If mismatch, build and deploy
cds-text-sync rp build --timeout 120
```

### Check and Modify Permissions
```bash
# Read current permissions (read-only from CLI)
cds-text-sync rp permissions --timeout 5

# If a command is blocked:
# → The human must open Settings window in the daemon dashboard
# → Uncheck the blocked operation in the Permissions tab
# → Click Apply
```

## Architecture Notes (for LLM understanding)

### Filesystem
```
cds-text-sync/
├── Project_daemon.py                  ← CODESYS entry point
├── src/ide_bridge/
│   ├── ide_reverse_pipe_loop.py       ← Main polling loop + handle_command()
│   ├── ide_daemon_ui.py               ← WinForms dashboard + Settings window
│   ├── ide_online_helpers.py          ← Online API wrappers
│   └── ide_runtime_common.py          ← Layout, run_external_engine()
├── cli/
│   ├── cds_text_sync.py               ← Python CLI (argparse, routing)
│   ├── external_engine/               ← Python 3 scripts (engine_cli.py etc.)
│   ├── MANUAL.md                      ← This file
│   └── cicd-format.md                 ← CI/CD test plan format specification
```

### CI/CD Test Runner

`rp cicd --file <test>.json` executes a JSON test plan against the PLC.

**Location:** `<sync-folder>/.test/*.json`

**Format:** see **[cicd-format.md](cicd-format.md)**

```bash
# One test file
cds-text-sync rp cicd --file arithmetic.json --timeout 60

# All JSON tests from .test/
cds-text-sync rp cicd --timeout 120

# Use text output for a compact human summary
cds-text-sync --output text rp cicd --file arithmetic.json --timeout 60
```

**How it works:**
1. The daemon reads every JSON plan from `.test/` unless `--file` is provided.
2. Each plan must explicitly set `"application": "ApplicationName"`.
3. Before each plan, the daemon selects that application, connects/logs in, and starts it by default.
4. Steps run sequentially: `write` -> `wait` -> `read` -> `assert`.
5. On `FAIL`, the current test stops unless `continue_on_fail: true`.
6. The dashboard shows concise lines such as `Run test: arithmetic.json`, `PASS arithmetic.json (1/1)`, and `Test suite PASS (1/1)`.
7. The CLI returns the detailed JSON report, including the exact failing step and error message.

**Requirements:**
- The requested application exists in the active CODESYS project.
- The target PLC/device can be reached by the project online configuration or by plan `ip`.
- Tested FB instances are declared and called from `MAIN`.

**Minimal plan:**

```json
{
  "name": "CI/CD Quick Test",
  "application": "CI_CD_Application",
  "start": false,
  "timeout": 10000,
  "tests": [
    {
      "name": "FB_Arithmetic add",
      "timeout": 5000,
      "steps": [
        { "action": "write", "variable": "MAIN.fbArith.rA", "value": 10.0 },
        { "action": "write", "variable": "MAIN.fbArith.rB", "value": 3.0 },
        { "action": "write", "variable": "MAIN.fbArith.eOp", "value": 0 },
        { "action": "write", "variable": "MAIN.fbArith.xExecute", "value": true },
        { "action": "wait", "ms": 200 },
        { "action": "assert", "variable": "MAIN.fbArith.xDone", "expected": true },
        { "action": "read", "variable": "MAIN.fbArith.rResult", "expected": 13.0, "tolerance": 0.001 },
        { "action": "write", "variable": "MAIN.fbArith.xExecute", "value": false }
      ]
    }
  ]
}
```

Use `"start": false` when the application is already running and you only want to execute test steps. With the updated daemon code, an already-running application is also accepted when `start` is omitted.

**Failure diagnostics:**

```bash
cds-text-sync rp cicd --file arithmetic.json --timeout 120
```

The dashboard intentionally stays short. Use CLI output for details such as missing `application`, connection/login errors, invalid variable names, or failed assertions.

**Important: pass-through FB call**

`MAIN` must call the FB in pass-through style, otherwise online writes to FB inputs are overwritten:

```iecst
// Wrong: fixed values overwrite online writes
fbArith(rA := 0.0, rB := 0.0, eOp := 0, xExecute := FALSE);

// Correct: inputs are read from their own current values
fbArith(rA := fbArith.rA, rB := fbArith.rB,
        eOp := fbArith.eOp, xExecute := fbArith.xExecute);
```

After writing `MAIN.fbArith.rA := 10.0` through the online API, `MAIN` reads `fbArith.rA` and passes it into the FB. The result appears in `MAIN.fbArith.rResult`.

**⚠️ Rising-edge vs. continuous execution for online tests**

When testing FBs via the online API, each `write` is committed individually
through `write_prepared_values`. Between writes, the PLC may or may not
complete a cycle. If an FB uses a rising-edge trigger
(`IF xExecute AND NOT xPrev THEN ...`), the transition from `FALSE` to `TRUE`
can be **lost** when the last `write xExecute=false` of one test and the first
`write xExecute=true` of the next test happen faster than the PLC cycle time.

**Recommendation:** for FBs tested via the online API, prefer **continuous
execution** over rising-edge:

```iecst
// ❌ Risky: rising edge can be lost in online writes
IF xExecute AND NOT xPrev THEN
    rResult := rA + rB;
    xDone := TRUE;
END_IF
IF NOT xExecute THEN xDone := FALSE; END_IF
xPrev := xExecute;

// ✅ Safe: executes every cycle while xExecute is TRUE
IF xExecute THEN
    rResult := rA + rB;
    xDone := TRUE;
ELSE
    xDone := FALSE;
    rResult := 0.0;   // optional: clear outputs
END_IF
```

If rising-edge is required for production, add a `wait` step between
`xExecute=false` and the next `xExecute=true` in the test plan:

```json
{"action": "write", "variable": "MAIN.fbArith.xExecute", "value": false},
{"action": "wait", "ms": 100},
{"action": "write", "variable": "MAIN.fbArith.rA", "value": 5.0},
{"action": "write", "variable": "MAIN.fbArith.xExecute", "value": true}
```

**⚠️ FB state persists between CICD test cases and test files**

The `cicd` runner does **not** reset FB instance variables between tests.
If test A leaves `fbArith.xDone = TRUE` and test B does not write `xExecute`,
the stale value persists. Always reset outputs in each test or design FBs
that clear their own outputs when `xExecute` goes `FALSE`.

**ST syntax notes:**
- `END_FUNCTION_BLOCK` / `END_FUNCTION` is not needed in `.st`; the CODESYS IDE adds it.
- The CODESYS API stores declaration and implementation separately.
- `.st` separator: `// --- implementation ---`
- Python type annotations such as `def fn(raw: str)` do not work in IronPython 2.7.

**Manual check after a test cycle:**
```bash
# Make sure the variable is readable
cds-text-sync rp read_variable --name MAIN.fbArith.rResult --timeout 25

# Write and read directly
cds-text-sync rp write_variable --name MAIN.fbArith.rA --value 10.0 --timeout 25
cds-text-sync rp read_variable --name MAIN.fbArith.rA --timeout 25
```

### update_pou

Directly write declaration/implementation into a POU from an `.st` file.

```bash
cds-text-sync rp update_pou --name MAIN --app CI_CD_Application \
  --st_path "CODESYS_Linux_SL/PLC Logic/CI_CD_Application/MAIN.st" --timeout 25
```

Use this when `sync_import_text` cannot update `MAIN` because of a `return_type` error in `import_native`.

**Tip:** `update_pou` is often faster and more reliable than `sync_import_text`
for single-POU changes. After `update_pou`, run `build` and then
`connect_to_device` to deploy to the PLC (see **Deploy Workflow** above).

You can update multiple POUs in sequence:

```bash
cds-text-sync rp update_pou --name FB_Scale --app CI_CD_Application \
  --st_path "CODESYS_Linux_SL/PLC Logic/CI_CD_Application/FB_Scale.st" --timeout 25
cds-text-sync rp update_pou --name FB_RangeCheck --app CI_CD_Application \
  --st_path "CODESYS_Linux_SL/PLC Logic/CI_CD_Application/FB_RangeCheck.st" --timeout 25
cds-text-sync rp build --timeout 120
cds-text-sync rp connect_to_device --timeout 60
```

Internally, it writes `textual_declaration.text` / `textual_implementation.text` through `.replace()` as a fallback when `.text = value` is read-only.

### Build Diagnostics

```bash
# Build and save the report
cds-text-sync rp build --output build-report.json --timeout 120 2>&1; cat build-report.json | python -m json.tool | head -40
```

**Known compile errors:**
| Code | Cause | Fix |
|-----|---------|--------|
| `C0077` | Unknown type such as TON or TP | Add the required library in Library Manager |
| `C0035` | Instance expected | Check the variable declaration |

### Permissions storage
- Config stored in `cds-daemon-config` project property (JSON)
- Read by daemon on startup
- Modified only through Settings window in the daemon dashboard
- CLI reads via `rp permissions` but cannot change

### Daemon lifecycle
1. User runs `Project_daemon.py` in CODESYS
2. `exec()` → `ide_reverse_pipe_loop.py` → `run_loop()`
3. Startup: log version + sync folder status, show WinForms dashboard
4. Poll: every N ms (configurable), connect to CLI pipe, read command, execute, respond
5. Stop: click "Stop Daemon" → `running=False` → loop exits → window closes → script ends cleanly
6. To restart: just run the script again
