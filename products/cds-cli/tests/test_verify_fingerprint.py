# -*- coding: utf-8 -*-
"""The workspace fingerprint ``cts verify`` hands to the IDE daemon.

The fingerprint is the identity half of the build handshake: the CLI scans the
sync folder, sends the digest with the build request, and the daemon compares
it with the folder it is looking at before its compiler verdict is credited.
So what the scan *includes* decides whether a real verdict is credited or
thrown away as ``stale_ide``.

These are characterization tests of the scan as it works today: every regular
file below the sync root, minus ``.git`` and ``.dump``. They pin that scope
file by file -- including the sync-root siblings an IDE keeps next to
``project-view/`` -- so the scope can be changed deliberately and visibly
rather than by accident.
"""

from __future__ import annotations

import os

from cds_cli.verify import fingerprint as verify_fingerprint


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


# -- the shape of the answer --------------------------------------------------


class TestTheScanAnswer:
    def test_an_empty_folder_is_complete(self, tmp_path):
        digest, complete, errors = _scan(tmp_path)

        assert complete is True
        assert errors == []
        assert len(digest) == 64

    def test_the_digest_is_stable_across_runs(self, tmp_path):
        _write(tmp_path, "project-view/POUs/PLC_PRG.st")

        assert _digest(tmp_path) == _digest(tmp_path)

    def test_content_changes_the_digest(self, tmp_path):
        path = _write(tmp_path, "project-view/POUs/PLC_PRG.st")

        before = _digest(tmp_path)
        _write(tmp_path, "project-view/POUs/PLC_PRG.st", "PROGRAM PLC_PRG\n")

        assert _digest(tmp_path) != before
        assert os.path.isfile(path)

    def test_a_rename_changes_the_digest(self, tmp_path):
        _write(tmp_path, "project-view/POUs/PLC_PRG.st")
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


# -- what the scan currently includes -----------------------------------------


class TestCurrentScope:
    """Today the scan is the whole sync root, not the workspace the import owns."""

    def test_every_regular_file_below_the_root_is_hashed(self, tmp_path):
        _write(tmp_path, "project-view/POUs/PLC_PRG.st")

        for relative in (
            "project-view/POUs/PLC_PRG.st",
            "loose.txt",
            "nested/deeper/loose.txt",
        ):
            _write(tmp_path, relative)
            digest = _digest(tmp_path)
            _write(tmp_path, relative, "changed\n")
            assert _digest(tmp_path) != digest, relative

    def test_a_nested_dotted_directory_is_skipped_at_any_depth(self, tmp_path):
        """``.git``/``.dump`` are excluded wherever they appear, not just at the top."""
        _write(tmp_path, "project-view/POUs/PLC_PRG.st")
        before = _digest(tmp_path)

        _write(tmp_path, "project-view/POUs/.dump/snapshot-1.xml", "<x/>\n")
        _write(tmp_path, "project-view/POUs/.git/HEAD", "ref: refs/heads/main\n")

        assert _digest(tmp_path) == before

    def test_the_top_level_generated_directories_are_skipped(self, tmp_path):
        _write(tmp_path, "project-view/POUs/PLC_PRG.st")
        before = _digest(tmp_path)

        _write(tmp_path, ".dump/IDE.xml", "<x/>\n")
        _write(tmp_path, ".git/HEAD", "ref: refs/heads/main\n")

        assert _digest(tmp_path) == before

    def test_the_ides_own_session_files_at_the_sync_root_are_hashed(self, tmp_path):
        """The live-workspace bug, pinned: these change without any cts command.

        A CODESYS project kept in the same folder as its sync root rewrites
        ``*.~u`` (session lock), ``*.project`` (on every save), ``*.opt`` and
        ``*.precompilecache`` whenever it runs. They are not workspace content
        -- nothing exports or imports them -- yet today they are inside the
        digest, which is what makes the fingerprint differ on every call.
        """
        _write(tmp_path, "project-view/POUs/PLC_PRG.st")
        before = _digest(tmp_path)

        _write(tmp_path, "VKO-live.~u", "alice:4711:2026-10-05T09:00:00\n")
        _write(tmp_path, "VKO-live.project", "binary-ish project state\n")
        _write(tmp_path, "VKO-live-1.opt", "<options/>\n")
        _write(tmp_path, "VKO-live_project.precompilecache", "<cache/>\n")

        assert _digest(tmp_path) != before


# -- what it leaves out -------------------------------------------------------


class TestSymlinksAndFailures:
    def test_a_symlink_is_not_followed_or_hashed(self, tmp_path):
        _write(tmp_path, "project-view/POUs/PLC_PRG.st")
        os.symlink(
            str(tmp_path / "project-view" / "POUs" / "PLC_PRG.st"),
            str(tmp_path / "project-view" / "POUs" / "alias.st"),
        )

        before = _digest(tmp_path)
        target = str(tmp_path / "project-view" / "POUs" / "PLC_PRG.st")
        os.remove(target)

        assert _digest(tmp_path) != before

    def test_an_unreadable_file_is_reported_instead_of_hashed(self, tmp_path, monkeypatch):
        _write(tmp_path, "project-view/POUs/PLC_PRG.st")

        real_open = open

        def deny(path, mode="r", *args, **kwargs):
            if mode == "rb" and str(path).endswith("PLC_PRG.st"):
                raise OSError("permission denied")
            return real_open(path, mode, *args, **kwargs)

        monkeypatch.setattr("builtins.open", deny)

        _digest_value, complete, errors = _scan(tmp_path)

        assert complete is False
        assert len(errors) == 1
        assert errors[0].startswith("project-view/POUs/PLC_PRG.st: ")

    def test_a_directory_is_not_a_file(self, tmp_path):
        os.makedirs(str(tmp_path / "project-view" / "POUs" / "empty.st"))

        _digest_value, complete, errors = _scan(tmp_path)

        assert complete is True
        assert errors == []
