"""The bridge command registry must stay aligned with its dispatch table.

command_registry is the single source of truth for daemon commands: the
reverse-pipe loop builds _DISPATCH from DISPATCH_SPECS, resolves aliases
through ALIASES, and serves HELP_TEXT as the daemon's help output. These tests
pin the three tables against each other and against the rule that decides
which commands skip the deny list.
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "products" / "codesys-host" / "src" / "ide_bridge"
if str(BRIDGE) not in sys.path:
    sys.path.insert(0, str(BRIDGE))


# The exact permission-exempt set, pinned on purpose. Every name here was
# audited in its handler against the rule in command_registry: a command is
# exempt only when it is strictly read-only -- it does not modify the project,
# the PLC, the sync folder's tracked content, any file outside .dump/, or
# daemon state that changes what a later command does. Adding a command here
# weakens the deny list, so the set must change deliberately, with the handler
# read first.
READ_ONLY_EXEMPT = frozenset([
    # daemon lifecycle and introspection
    "ping", "status", "timeout_profile", "help", "stop_daemon", "permissions",
    # project and object inspection
    "project_info", "project_tree", "read_object", "project_list",
    "list_devices", "explore", "probe", "discover", "diagnose_online",
    # PLC reads (an existing session only; no login, download or update)
    "read_variable", "read_variables", "application_state", "device_status",
    "test_online",
    # PLC file inspection and CRC reads
    "app_crc", "app_info", "app_history", "plc_crc",
    # sync state read-back
    "sync", "last_result", "generate_docs",
])

# A representative sample of commands that write or change the PLC session.
# None of these may ever appear in NO_PERMISSION; the list would only grow if
# a command like application_tree (optional --output file) were reclassified.
MUTATING = frozenset([
    "connect_to_device", "disconnect_from_device", "download",
    "write_variable", "write_variables", "export", "build",
    "sync_export", "sync_import", "sync_export_text", "sync_import_text",
    "update_pou", "delete_pou", "cicd", "reset_plc", "start_plc", "stop_plc",
    "create_boot_app", "source_download", "application_tree", "plc_files",
    "plc_download", "plc_upload", "export_csv", "export_st", "plc_log",
    "project_open", "project_close", "set_sync_folder", "set_simulation_mode",
    "set_credentials", "read_log",
])


def test_registry_matches_reverse_pipe_dispatch():
    import command_registry
    import ide_reverse_pipe_loop as daemon

    assert set(daemon._DISPATCH) == set(command_registry.DISPATCH_NAMES)


def test_help_text_covers_every_command_exactly():
    import command_registry

    assert set(command_registry.HELP_TEXT) == set(command_registry.DISPATCH_NAMES)


def test_aliases_resolve_and_do_not_shadow_commands():
    import command_registry

    dispatch = set(command_registry.DISPATCH_NAMES)
    assert all(
        command_registry.canonical_name(alias) in dispatch
        for alias in command_registry.ALIASES
    )
    # An alias sharing a command's name would make dispatch depend on which
    # table the caller consulted first.
    assert not (set(command_registry.ALIASES) & dispatch)


def test_legacy_protocol_names_stay_unambiguous():
    import command_registry

    # `stop` stops the daemon; the user-facing PLC stop is a separate command.
    assert command_registry.canonical_name("stop") == "stop_daemon"
    assert "stop_plc" in command_registry.DISPATCH_NAMES
    # `compare` is the CRC comparison, not the `cts compare` text comparison.
    assert command_registry.canonical_name("compare") == "plc_crc"
    assert command_registry.canonical_name("unknown_command") == "unknown_command"


def test_no_permission_is_the_pinned_read_only_set():
    import command_registry

    assert set(command_registry.NO_PERMISSION) == READ_ONLY_EXEMPT
    assert set(command_registry.NO_PERMISSION) <= set(command_registry.DISPATCH_NAMES)


def test_no_permission_never_exempts_a_writing_command():
    import command_registry

    assert not (MUTATING & set(command_registry.NO_PERMISSION))
    assert MUTATING <= set(command_registry.DISPATCH_NAMES)
