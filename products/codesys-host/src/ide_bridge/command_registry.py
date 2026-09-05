# -*- coding: utf-8 -*-

"""Plain command metadata shared by the IronPython bridge and tooling.

Keep this module data-only: it must load in IronPython 2.7 and CPython without
pulling in CODESYS or CLI modules.
"""

ALIASES = {
    "connect": "connect_to_device",
    "disconnect": "disconnect_from_device",
    "app": "application_state",
    "proj": "project_info",
    "tree": "project_tree",
}

NO_PERMISSION = frozenset([
    "ping", "status", "timeout_profile", "help", "stop", "permissions", "sync",
    "project_info", "project_tree", "read_object", "explore",
    "project_list", "list_devices", "diagnose_online", "discover",
])


def canonical_name(name):
    """Return the canonical command name for an alias or the input itself."""
    return ALIASES.get(name, name)


DISPATCH_NAMES = frozenset([
    "project_tree", "read_object", "connect_to_device", "download",
    "read_variable", "write_variable", "read_variables", "write_variables",
    "export", "build", "device_status", "test_online", "sync_export",
    "sync_import", "sync_compare", "sync_export_text", "sync_import_text",
    "sync_compare_text", "update_pou", "delete_pou", "cicd", "read_log",
    "reset_plc", "source_download", "probe", "application_tree", "plc_files",
    "plc_log", "plc_download", "plc_upload", "export_csv", "export_st",
    "app_crc", "app_history", "plc_crc", "compare", "stop", "ping", "status", "timeout_profile",
    "project_info", "application_state", "disconnect_from_device", "explore",
    "set_sync_folder",
    "sync", "help", "start_plc", "stop_plc", "create_boot_app", "app_info",
    "permissions", "project_open", "project_close", "project_list",
    "list_devices", "set_simulation_mode", "set_credentials", "diagnose_online",
    "discover",
])

DISPATCH_SPECS = {
    "project_tree": ("direct", "_cmd_project_tree"),
    "read_object": ("direct", "_cmd_read_object"),
    "connect_to_device": ("direct", "_cmd_connect_to_device"),
    "download": ("direct", "_cmd_download"),
    "read_variable": ("direct", "_cmd_read_variable"),
    "write_variable": ("direct", "_cmd_write_variable"),
    "read_variables": ("direct", "_cmd_read_variables"),
    "write_variables": ("direct", "_cmd_write_variables"),
    "export": ("direct", "_cmd_export"),
    "build": ("direct", "_cmd_build"),
    "device_status": ("direct", "_cmd_device_status"),
    "test_online": ("direct", "_cmd_test_online"),
    "sync_export": ("direct", "_cmd_sync_export"),
    "sync_import": ("direct", "_cmd_sync_import"),
    "sync_compare": ("direct", "_cmd_sync_compare"),
    "sync_export_text": ("direct", "_cmd_sync_export_text"),
    "sync_import_text": ("direct", "_cmd_sync_import_text"),
    "sync_compare_text": ("direct", "_cmd_sync_compare_text"),
    "update_pou": ("direct", "_cmd_update_pou"),
    "delete_pou": ("direct", "_cmd_delete_pou"),
    "cicd": ("direct", "_cmd_cicd"),
    "read_log": ("direct", "_cmd_read_log"),
    "reset_plc": ("direct", "_cmd_reset_plc"),
    "source_download": ("direct", "_cmd_source_download"),
    "probe": ("direct", "_cmd_probe_oa"),
    "application_tree": ("direct", "_cmd_application_tree"),
    "plc_files": ("direct", "_cmd_plc_files"),
    "plc_log": ("direct", "_cmd_plc_log"),
    "plc_download": ("direct", "_cmd_plc_download"),
    "plc_upload": ("direct", "_cmd_plc_upload"),
    "export_csv": ("direct", "_cmd_export_csv"),
    "export_st": ("direct", "_cmd_export_st"),
    "app_crc": ("direct", "_cmd_app_crc"),
    "app_history": ("direct", "_cmd_app_history"),
    "plc_crc": ("direct", "_cmd_compare_crc"),
    # Legacy name. It says "compare" in the daemon log while doing something
    # entirely unlike `cts compare` (that one is sync_compare_text), so the log
    # read as a folder comparison mysteriously building the project -- the
    # build being CODESYS generating code inside the login attempt. Kept so an
    # older CLI against a newer daemon still works.
    "compare": ("direct", "_cmd_compare_crc"),
    "stop": ("direct", "_handle_stop"),
    "ping": ("direct", "_handle_ping"),
    "status": ("direct", "_handle_status"),
    "timeout_profile": ("direct", "_handle_timeout_profile"),
    "project_info": ("noarg", "_cmd_project_info"),
    "set_sync_folder": ("direct", "_cmd_set_sync_folder"),
    "application_state": ("noarg", "_cmd_application_state"),
    "disconnect_from_device": ("noarg", "_cmd_disconnect_from_device"),
    "explore": ("noarg", "_cmd_explore_api"),
    "sync": ("noarg", "_cmd_sync_info"),
    "help": ("noarg", "_cmd_help"),
    "start_plc": ("noarg", "_cmd_start_plc"),
    "stop_plc": ("noarg", "_cmd_stop_plc"),
    "create_boot_app": ("noarg", "_cmd_create_boot_app"),
    "app_info": ("noarg", "_cmd_app_info"),
    "permissions": ("noarg", "_cmd_permissions"),
    "project_open": ("direct", "_cmd_project_open"),
    "project_close": ("noarg", "_cmd_project_close"),
    "project_list": ("noarg", "_cmd_project_list"),
    "list_devices": ("noarg", "_cmd_list_devices"),
    "set_simulation_mode": ("direct", "_cmd_set_simulation_mode"),
    "set_credentials": ("direct", "_cmd_set_credentials"),
    "diagnose_online": ("noarg", "_cmd_diagnose_online"),
    "discover": ("direct", "_cmd_discover"),
}

HELP_TEXT = {
"ping": "Check daemon liveness and cached PLC state",
"status": "Get daemon, project, sync-folder, and cached PLC state",
"stop": "Stop the daemon",
"application_state": "Get PLC application state (run/stop)",
"project_info": "Get project information",
"set_sync_folder": "Set project sync folder [--path PATH] [--save]; omit path to use the saved project directory",
"project_tree": "Get project object tree [--depth N]",
"read_object": "Read one project object [--path PATH | --name NAME | --guid GUID]",
"connect_to_device": "Connect to PLC [--ip IP] [--gatewayName NAME] — best practice: connect in CODESYS UI before starting daemon. If not, user must approve the connection dialog in CODESYS within ~2 minutes or the command times out.",
"disconnect_from_device": "Disconnect from PLC",
"download": "Force a FULL download of the active app to the PLC (login with force-download; needed after adding new GVL/DUT/POU). [--start 0|1, default 1]",
"read_variable": "Read a PLC variable --name VAR",
"write_variable": "Write a PLC variable --name VAR --value VAL",
"device_status": "Get device status",
"export": "Export project snapshot [--output PATH]",
"build": "Build the active application [--output PATH]",
"test_online": "Test online connection helpers",
"explore": "Explore available APIs",
"help": "Show this help",
"read_log": "Read system/PLC log messages [--last N] [--clear]",
"start_plc": "Start the PLC application",
"stop_plc": "Stop the PLC application",
"reset_plc": "Reset PLC [--kind warm|cold|origin]",
"create_boot_app": "Create boot application on PLC",
"source_download": "Download source from PLC [--output DIR]",
"update_pou": "Edge case: update ONE object's text from .st [--name NAME] [--app APP] --st_path PATH. Prefer sync_import_text for the normal disk->IDE flow",
"delete_pou": "Delete POU/Function/FunctionBlock [--name NAME] [--app APP]",
"probe": "Probe OnlineApplication for variable/symbol APIs",
"read_variables": 'Batch-read expressions {"names": [...]} -> per-item value/read_ok/read_error',
"write_variables": 'Batch-write {"items": [{name,value}]} -> per-item written/write_error',
"application_tree": "Walk the application OBJECT tree [--depth N] [--values] [--pattern FILTER] [--flat] [--output PATH]",
"plc_files": "List files on PLC [--path /]",
"plc_download": "Download file from PLC --src PATH [--dest PATH]",
"plc_upload": "Upload file to PLC --src PATH --dest PLC_PATH [--overwrite 0|1]",
"export_csv": "Export PLC variable tree as CSV [--output PATH] [--values]",
"export_st": "Export project POU source code as .st files [--output DIR]",
"app_crc": "Get Application CRC and metadata from PLC",
"app_history": "Log CRC to .dump/app_history.json [--read to just view history]",
"sync": "Show sync folder info and .dump state",
"sync_export": "Export Native XML snapshot to .dump/ [--output PATH]",
"sync_import": "Low-level: import a raw .dump/ XML snapshot back into project [--input PATH]. For text edits use sync_import_text instead",
"sync_compare": "Compare project tree against .dump/ snapshot [--against PATH]",
"sync_export_text": "IDE->disk: export Native XML and refresh project-view/ text files (local edits are kept by default)",
"sync_import_text": "disk->IDE (preferred): build IMPORT.xml from project-view/ and apply to project. Disk wins on conflicts; requires offline (disconnect first)",
"sync_compare_text": "Compare project against project-view/ (diff report)",
"cicd": "Run CI/CD test plan --file path [--timeout N]",
"permissions": "Show daemon security config (read-only)",
"plc_log": "Read PLC log [--file codesyscontrol.log] [--tail N] [--output DIR]",
"app_info": "Get detailed info about application on PLC",
"plc_crc": "Compare IDE project CRC with PLC Application.crc",
"compare": "Deprecated alias for plc_crc",
}
