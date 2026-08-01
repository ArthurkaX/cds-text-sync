"""
analyze_helpers.py - Shared helpers for the ``cts analyze`` test tier.

Not a test module itself (pytest collects test_*.py only).
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys

FIXTURE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "analyze")
)


def fixture_path(*parts):
    return os.path.join(FIXTURE_DIR, *parts)


def fixture_project_view():
    return fixture_path("project-view")


def copy_fixture(dest):
    """Copy the whole analyze fixture into *dest* and return dest."""
    shutil.copytree(fixture_path("project-view"), os.path.join(dest, "project-view"))
    return dest


def run_cli(argv):
    """Run the CLI in-process, returning (exit_code, stdout, stderr)."""
    from cds_text_sync.main import main

    old_argv = sys.argv
    sys.argv = ["cts"] + list(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        finally:
            sys.argv = old_argv
    return code, stdout.getvalue(), stderr.getvalue()


def run_analyze_json(workspace, extra=None):
    """Run ``cts analyze`` against a workspace in JSON mode.

    Returns the parsed JSON document.
    """
    import json

    argv = ["analyze", "--workspace", workspace, "--format", "json"]
    if extra:
        argv.extend(extra)
    code, out, err = run_cli(argv)
    data = json.loads(out)
    data["_exit"] = code
    data["_stderr"] = err
    return data
