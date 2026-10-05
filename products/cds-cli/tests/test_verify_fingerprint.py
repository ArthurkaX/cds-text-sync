# -*- coding: utf-8 -*-
"""The workspace fingerprint ``cts verify`` hands to the IDE daemon.

The fingerprint is the identity half of the build handshake: the CLI scans the
workspace, sends the digest with the build request, and the daemon compares it
with the folder it is looking at before its compiler verdict is credited. So
what the scan *includes* decides whether a real verdict is credited or thrown
away as ``stale_ide``.

The scan covers the workspace the export writes and the import reads -- the
view root, ``project-view/`` by default -- not the sync folder around it. A
CODESYS project kept in its own sync folder rewrites ``*.~u``, ``*.project``,
``*.opt`` and ``*.precompilecache`` next to ``project-view/`` while the IDE
runs; hashing those made the digest differ on every call and masked the
compiler.

The daemon-side twin of this scan is covered in
``tests/unit/test_workspace_fingerprint_twin.py``.
"""

from __future__ import annotations

import json
import os

from cds_cli.verify import fingerprint as verify_fingerprint
from cds_text_sync.engine._workspace_fingerprint import workspace_files


def _scan(root):
    return verify_fingerprint.workspace_fingerprint(str(root))


def _digest(root):
    digest, complete, errors = _scan(root)
    assert complete is True, errors
    return digest


def _write(root, relative, text="x\n"):
    """Write one file, creating its parents. Returns the absolute path."""
    path = os.path.join(str(root), *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def _project(tmp_path, **settings):
    """A sync folder with a project-view/ and optional project settings."""
    _write(tmp_path, "project-view/POUs/PLC_PRG.st", "PROGRAM PLC_PRG\n")
    if settings:
        _write(tmp_path, "cds-text-sync.json", json.dumps(settings))
    return tmp_path


# -- the shape of the answer --------------------------------------------------


class TestTheScanAnswer:
    def test_an_empty_folder_is_complete(self, tmp_path):
        digest, complete, errors = _scan(tmp_path)

        assert complete is True
        assert errors == []
        assert len(digest) == 64

    def test_an_unexported_folder_is_its_own_workspace(self, tmp_path):
        """No view root yet: the scan covers the folder instead of failing."""
        _write(tmp_path, "PLC_PRG.st")

        assert workspace_files(tmp_path) == ["PLC_PRG.st"]

    def test_the_digest_is_stable_across_runs(self, tmp_path):
        _project(tmp_path)

        assert _digest(tmp_path) == _digest(tmp_path)

    def test_content_changes_the_digest(self, tmp_path):
        path = _write(tmp_path, "project-view/POUs/PLC_PRG.st")

        before = _digest(tmp_path)
        _write(tmp_path, "project-view/POUs/PLC_PRG.st", "PROGRAM PLC_PRG\n")

        assert _digest(tmp_path) != before
        assert os.path.isfile(path)

    def test_a_rename_changes_the_digest(self, tmp_path):
        _project(tmp_path)
        before = _digest(tmp_path)

        os.rename(
            str(tmp_path / "project-view" / "POUs" / "PLC_PRG.st"),
            str(tmp_path / "project-view" / "POUs" / "PLC_MAIN.st"),
        )

        assert _digest(tmp_path) != before

    def test_the_absolute_path_is_not_part_of_the_digest(self, tmp_path):
        """Two checkouts of the same content fingerprint the same."""
        left = tmp_path / "left"
        right = tmp_path / "right"
        for root in (left, right):
            _write(root, "project-view/POUs/PLC_PRG.st", "PROGRAM PLC_PRG\n")

        assert _digest(left) == _digest(right)


# -- what the scan covers -----------------------------------------------------


class TestScope:
    """The scope is the view root: what export writes and import reads."""

    def test_only_the_view_root_is_hashed(self, tmp_path):
        _project(tmp_path)

        assert workspace_files(tmp_path) == ["POUs/PLC_PRG.st"]

    def test_a_change_inside_the_view_root_changes_the_digest(self, tmp_path):
        _project(tmp_path)
        before = _digest(tmp_path)

        _write(tmp_path, "project-view/GVLs/GVL.st", "VAR_GLOBAL x : INT; END_VAR\n")

        assert _digest(tmp_path) != before

    def test_the_sync_root_beside_the_view_root_is_not_hashed(self, tmp_path):
        """Files next to project-view/ are not workspace content.

        The IDE rewrites its own session and project files there while the user
        works; a digest that watched them reported a new workspace on every
        call, so the daemon's real verdict never survived the handshake.
        """
        _project(tmp_path)
        before = _digest(tmp_path)

        _write(tmp_path, "VKO-live.~u", "alice:4711:2026-10-05T09:00:00\n")
        _write(tmp_path, "VKO-live.project", "binary-ish project state\n")
        _write(tmp_path, "VKO-live-1.opt", "<options/>\n")
        _write(tmp_path, "VKO-live_project.precompilecache", "<cache/>\n")
        _write(tmp_path, "loose-notes.txt", "scratch\n")

        assert _digest(tmp_path) == before

    def test_the_ide_session_lock_changing_does_not_move_the_digest(self, tmp_path):
        """The reported symptom: the same disk, seven different fingerprints."""
        _project(tmp_path)

        digests = []
        for minute in range(7):
            _write(tmp_path, "VKO-live.~u", "alice:4711:2026-10-05T09:{0:02d}\n".format(minute))
            digests.append(_digest(tmp_path))

        assert len(set(digests)) == 1

    def test_generated_state_at_the_top_of_the_scope_is_skipped(self, tmp_path):
        _project(tmp_path)
        before = _digest(tmp_path)

        _write(tmp_path, ".dump/IDE.xml", "<x/>\n")
        _write(tmp_path, ".git/HEAD", "ref: refs/heads/main\n")
        _write(tmp_path, ".backup/2026-10-05/project.zip", "zip\n")

        assert _digest(tmp_path) == before

    def test_tool_owned_dotted_entries_at_the_top_of_the_scope_are_skipped(self, tmp_path):
        """The same rule the folder writer uses when it decides what it owns.

        A dot-named entry at the top of the view root is tool-owned -- the
        captured frames of ``.cds-visu`` are written by ``cts visu
        capture-frame``, not by an import -- while a dot-named folder deeper in
        the tree is the project's own content.
        """
        _project(tmp_path)
        before = _digest(tmp_path)

        _write(tmp_path, "project-view/.cds-visu/frames/PUMP.json", "{}\n")

        assert _digest(tmp_path) == before

    def test_an_explicit_view_root_is_honoured(self, tmp_path):
        _write(tmp_path, "cds-text-sync.json", json.dumps({"view_root": "views"}))
        _write(tmp_path, "views/POUs/PLC_PRG.st", "PROGRAM PLC_PRG\n")
        _write(tmp_path, "project-view/POUs/ignored.st", "PROGRAM IGNORED\n")

        assert workspace_files(tmp_path) == ["POUs/PLC_PRG.st"]

    def test_the_root_view_layout_scopes_to_the_sync_root(self, tmp_path):
        _write(tmp_path, "cds-text-sync.json", json.dumps({"layout": "root-view"}))
        _write(tmp_path, "POUs/PLC_PRG.st", "PROGRAM PLC_PRG\n")
        _write(tmp_path, ".dump/IDE.xml", "<x/>\n")

        # The settings file is tracked content in this layout, so it is part of
        # the workspace; the generated .dump/ still is not.
        assert workspace_files(tmp_path) == ["POUs/PLC_PRG.st", "cds-text-sync.json"]

    def test_a_sync_folder_inside_the_project_folder_scopes_the_same(self, tmp_path):
        """The layout of the reported bug: sync folder == project folder.

        The IDE writes its own files beside project-view/; the digest has to
        ignore them there exactly as it does in a separate sync folder.
        """
        _write(tmp_path, "VKO-live.project", "state\n")
        _write(tmp_path, "project-view/POUs/PLC_PRG.st", "PROGRAM PLC_PRG\n")
        before = _digest(tmp_path)

        _write(tmp_path, "VKO-live.project", "state, saved again\n")
        _write(tmp_path, "VKO-live.~u", "alice:4711:2026-10-05T09:00:00\n")

        assert _digest(tmp_path) == before


# -- what it leaves out -------------------------------------------------------


class TestSymlinksAndFailures:
    def test_a_symlink_is_not_followed_or_hashed(self, tmp_path):
        _project(tmp_path)
        os.symlink(
            str(tmp_path / "project-view" / "POUs" / "PLC_PRG.st"),
            str(tmp_path / "project-view" / "POUs" / "alias.st"),
        )

        before = _digest(tmp_path)
        target = str(tmp_path / "project-view" / "POUs" / "PLC_PRG.st")
        os.remove(target)

        assert _digest(tmp_path) != before

    def test_an_unreadable_file_is_reported_instead_of_hashed(self, tmp_path, monkeypatch):
        _project(tmp_path)

        real_open = open

        def deny(path, mode="r", *args, **kwargs):
            if mode == "rb" and str(path).endswith("PLC_PRG.st"):
                raise OSError("permission denied")
            return real_open(path, mode, *args, **kwargs)

        monkeypatch.setattr("builtins.open", deny)

        _digest_value, complete, errors = _scan(tmp_path)

        assert complete is False
        assert len(errors) == 1
        assert errors[0].startswith("POUs/PLC_PRG.st: ")

    def test_a_directory_is_not_a_file(self, tmp_path):
        os.makedirs(str(tmp_path / "project-view" / "POUs" / "empty.st"))

        _digest_value, complete, errors = _scan(tmp_path)

        assert complete is True
        assert errors == []
