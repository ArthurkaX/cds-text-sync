"""The bridge command registry must stay aligned with its dispatch table."""

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
    assert set(command_registry.NO_PERMISSION) <= set(command_registry.DISPATCH_NAMES)
    assert all(
        command_registry.canonical_name(alias) in command_registry.DISPATCH_NAMES
        for alias in command_registry.ALIASES
    )
