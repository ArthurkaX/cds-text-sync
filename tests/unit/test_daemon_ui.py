from __future__ import annotations

import os
import sys

from pathlib import Path

# Add ide_bridge to path
_IDE_BRIDGE = (
    Path(__file__).resolve().parent.parent.parent
    / "products"
    / "codesys-host"
    / "src"
    / "ide_bridge"
)
if str(_IDE_BRIDGE) not in sys.path:
    sys.path.insert(0, str(_IDE_BRIDGE))

from ide_daemon_ui import format_copy_command, format_instance_label


def test_format_instance_label_with_project():
    info = {
        "id": "ide-3684",
        "pid": 3684,
        "project": {
            "name": "VKO",
            "path": r"S:\Projects\VKO\VKO.project",
            "sync_folder": r"S:\_Active\VKO-Beumer",
        },
    }
    assert format_instance_label(info) == "IDE: ide-3684 · VKO"


def test_format_instance_label_no_project():
    info = {
        "id": "ide-3684",
        "pid": 3684,
        "project": None,
    }
    assert format_instance_label(info) == "IDE: ide-3684 · no project"


def test_format_instance_label_empty():
    pid = os.getpid()
    assert format_instance_label(None) == f"IDE: ide-{pid} · no project"
    assert format_instance_label({}) == f"IDE: ide-{pid} · no project"


def test_format_copy_command_with_project():
    info = {
        "id": "ide-3684",
        "pid": 3684,
        "project": {
            "name": "VKO",
            "path": r"S:\Projects\VKO\VKO.project",
            "sync_folder": r"S:\_Active\VKO-Beumer",
        },
    }
    cmd = format_copy_command(info)
    assert cmd == "!cts --target ide-3684 --expect-project VKO --help"


def test_format_copy_command_no_project():
    info = {
        "id": "ide-3684",
        "pid": 3684,
        "project": None,
    }
    cmd = format_copy_command(info)
    assert cmd == "!cts --target ide-3684 --help"


def test_format_copy_command_without_info_uses_this_pid():
    cmd = format_copy_command(None)
    assert cmd == f"!cts --target ide-{os.getpid()} --help"
