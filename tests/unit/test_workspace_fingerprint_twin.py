# -*- coding: utf-8 -*-
"""The daemon's workspace fingerprint must equal the CLI's.

``cts verify`` sends a digest of the workspace and the daemon compares it with
the folder it can see before the compiler's verdict is credited. The two sides
run in different interpreters on possibly different hosts, so the only thing
keeping a real verdict from being thrown away as ``stale_ide`` is that they
hash the same files the same way.

The two used to be separate copies of the same walk, and the copies drifted:
the CLI's excluded ``.git``/``.dump`` anywhere, the daemon's had no notion of
the view root at all, and both hashed the IDE's own session files sitting in
the sync folder. This test is the guard that the bridge imports the one
implementation instead of growing a second one.

The bridge modules are IronPython-only, so their CODESYS dependencies are
stubbed before import (same loader as ``test_build_message_identifier.py``).
"""

import importlib.util
import sys
from pathlib import Path

from cds_cli.verify import fingerprint as cli_fingerprint


BRIDGE_DIR = (
    Path(__file__).parent.parent.parent
    / "products"
    / "codesys-host"
    / "src"
    / "ide_bridge"
)

if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))


def _state_stub():
    module = type(sys)("ide_daemon_state")
    module._log = lambda *args, **kwargs: None
    module._get_active_project = lambda: (None, None)
    module._obj_name = lambda obj: ""
    return module


def _helpers_stub():
    module = type(sys)("ide_daemon_helpers")
    module._get_sync_folder = lambda *args, **kwargs: ""
    module._build_path = lambda obj: ""
    module._require_online_app = lambda: (
        None,
        {"ok": False, "error": "Not connected. Call connect_to_device first."},
    )
    return module


def _load_handlers_build():
    saved = {}
    for name, module in {
        "ide_daemon_state": _state_stub(),
        "ide_daemon_helpers": _helpers_stub(),
    }.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = module
    try:
        spec = importlib.util.spec_from_file_location(
            "ide_handlers_build_twin_under_test",
            BRIDGE_DIR / "ide_handlers_build.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


build = _load_handlers_build()


def _write(root, relative, text="x\n"):
    path = Path(str(root)) / Path(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _workspace(tmp_path):
    """The reported layout: the sync folder is the IDE's project folder."""
    _write(tmp_path, "project-view/POUs/PLC_PRG.st", "PROGRAM PLC_PRG\n")
    _write(tmp_path, "project-view/GVLs/GVL.st", "VAR_GLOBAL x : INT; END_VAR\n")
    _write(tmp_path, "VKO-live.project", "binary project state\n")
    _write(tmp_path, "VKO-live.~u", "alice:4711:2026-10-05T09:00:00\n")
    _write(tmp_path, "VKO-live-1.opt", "<options/>\n")
    _write(tmp_path, ".dump/IDE.xml", "<x/>\n")
    _write(tmp_path, ".git/HEAD", "ref: refs/heads/main\n")
    return tmp_path


def _cli(root):
    return cli_fingerprint.workspace_fingerprint(str(root))


class TestTheTwoSidesAgree:
    def test_one_workspace_produces_one_digest(self, tmp_path):
        _workspace(tmp_path)

        cli_digest, cli_complete, cli_errors = _cli(tmp_path)
        daemon_digest, daemon_complete = build._workspace_fingerprint(str(tmp_path))

        assert cli_errors == []
        assert cli_complete is True
        assert daemon_complete is True
        assert daemon_digest == cli_digest

    def test_the_agreement_holds_after_an_edit_inside_the_view_root(self, tmp_path):
        _workspace(tmp_path)
        before = build._workspace_fingerprint(str(tmp_path))[0]

        _write(tmp_path, "project-view/POUs/PLC_PRG.st", "PROGRAM PLC_PRG2\n")

        daemon_digest = build._workspace_fingerprint(str(tmp_path))[0]
        assert daemon_digest == _cli(tmp_path)[0]
        assert daemon_digest != before

    def test_an_ide_save_moves_neither_side(self, tmp_path):
        """The symptom in the field, on both sides of the pipe at once."""
        _workspace(tmp_path)
        cli_before = _cli(tmp_path)[0]
        daemon_before = build._workspace_fingerprint(str(tmp_path))[0]

        for minute in range(5):
            _write(tmp_path, "VKO-live.~u", "bob:99:2026-10-05T09:{0:02d}\n".format(minute))
            _write(tmp_path, "VKO-live.project", "saved at {0}\n".format(minute))

        assert _cli(tmp_path)[0] == cli_before
        assert build._workspace_fingerprint(str(tmp_path))[0] == daemon_before

    def test_the_empty_folder_digest_matches_too(self, tmp_path):
        _write(tmp_path, "project-view/POUs/.keep", "")

        assert build._workspace_fingerprint(str(tmp_path))[0] == _cli(tmp_path)[0]

    def test_a_sync_folder_beside_the_project_agrees_with_one_inside_it(self, tmp_path):
        """Same view root, two layouts, one digest."""
        inside = _workspace(tmp_path / "inside")
        beside = _workspace(tmp_path / "elsewhere")

        assert (
            build._workspace_fingerprint(str(inside))[0]
            == build._workspace_fingerprint(str(beside))[0]
        )


class TestTheDaemonWrapper:
    def test_an_unreadable_workspace_is_reported_incomplete(self, tmp_path, monkeypatch):
        _workspace(tmp_path)

        def boom(root):
            raise OSError("disk fell over")

        monkeypatch.setattr(build, "_workspace_scan", boom)

        assert build._workspace_fingerprint(str(tmp_path)) == ("", False)

    def test_a_partial_read_is_not_complete(self, tmp_path, monkeypatch):
        _workspace(tmp_path)

        real_open = open

        def deny(path, mode="r", *args, **kwargs):
            if mode == "rb" and str(path).endswith("PLC_PRG.st"):
                raise OSError("permission denied")
            return real_open(path, mode, *args, **kwargs)

        monkeypatch.setattr("builtins.open", deny)

        digest, complete = build._workspace_fingerprint(str(tmp_path))

        # A digest is still computed, but the daemon's answer shape has no room
        # for the per-file reasons, so only "not usable as evidence" survives.
        assert complete is False
        assert len(digest) == 64

    def test_the_wrapper_returns_the_pair_the_cli_expects(self, tmp_path):
        _workspace(tmp_path)

        result = build._workspace_fingerprint(str(tmp_path))

        assert isinstance(result, tuple)
        assert len(result) == 2
        digest, complete = result
        assert isinstance(digest, str) and len(digest) == 64
        assert complete is True
