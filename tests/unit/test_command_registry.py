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


def test_no_permission_entries_are_commands():
    import command_registry

    assert set(command_registry.NO_PERMISSION) <= set(command_registry.DISPATCH_NAMES)
