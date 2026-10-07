# -*- coding: utf-8 -*-
"""The offline engine child launched by ``cts engine`` resolves the real engine,
not a look-alike ``cds_text_sync`` in the caller's working directory."""

import subprocess

import pytest

from cds_cli import _cli_io


def test_engine_child_ignores_a_shadow_package_in_cwd(tmp_path, monkeypatch):
    shadow = tmp_path / "cds_text_sync" / "engine"
    shadow.mkdir(parents=True)
    (tmp_path / "cds_text_sync" / "__init__.py").write_text("")
    (shadow / "__init__.py").write_text("")
    (shadow / "engine_cli.py").write_text("raise SystemExit('SHADOW')\n")
    monkeypatch.chdir(tmp_path)

    captured = {}

    class _Proc:
        returncode = 0

        def wait(self):
            return 0

    def _fake_popen(cmd, env=None):
        captured["cmd"] = cmd
        captured["env"] = env
        return _Proc()

    real_popen = subprocess.Popen
    monkeypatch.setattr(_cli_io.subprocess, "Popen", _fake_popen)
    with pytest.raises(SystemExit):
        _cli_io.cmd_direct(["--help"])
    monkeypatch.setattr(_cli_io.subprocess, "Popen", real_popen)

    # Run the exact command line the CLI built, from the shadowed cwd.
    result = subprocess.run(
        captured["cmd"], env=captured["env"], capture_output=True, text=True
    )
    assert "SHADOW" not in result.stdout + result.stderr
    assert result.returncode == 0, result.stderr
