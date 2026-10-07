# -*- coding: utf-8 -*-
"""
test_coerce_bool.py — one truthy parser for the host, the engine and the CLI.

The daemon, the engine and the Settings window all read flags written by each
other, so their accepted spellings have to agree.  They did not: one copy
accepted "on" where another accepted "ok", which made the same snapshot field
mean two different things depending on which module read it.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _extra in (ROOT / "shared" / "src", ROOT / "products" / "codesys-host" / "src" / "ide_bridge"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from cts_shared.coerce import as_bool


@pytest.mark.parametrize(
    "value",
    ["1", "true", "True", "TRUE", " true ", "yes", "YES", "on", "ON", True],
)
def test_recognised_true_values(value):
    assert as_bool(value) is True


@pytest.mark.parametrize(
    "value",
    ["0", "false", "False", "FALSE", " false ", "no", "NO", "off", "OFF", False],
)
def test_recognised_false_values(value):
    assert as_bool(value, default=True) is False


@pytest.mark.parametrize("value", ["", "  ", "maybe", "ok", "2", None, [], {}])
def test_everything_else_is_the_default(value):
    assert as_bool(value) is False
    assert as_bool(value, default=True) is True


def test_bool_passthrough_keeps_the_value():
    assert as_bool(True) is True
    assert as_bool(False) is False


def test_the_two_snapshot_readers_agree_on_read_ok():
    """The field both used to parse differently ("on" vs "ok")."""
    import project_snapshooter
    import snapshot_compare

    for value in ("1", "true", "yes", "on", "ok", "", None, False):
        assert project_snapshooter._as_bool(value) == snapshot_compare._as_bool(value), value


def test_the_engine_settings_reader_agrees():
    from cds_text_sync.engine import _project_settings

    for value in ("1", "true", "yes", "on", "off", "no", "0", "false", "", None, True, False):
        assert _project_settings._safe_bool(value) == as_bool(value), value


def test_the_build_handler_reader_agrees():
    import ide_handlers_build

    for value in ("1", "true", "yes", "on", "nonsense", "", None, True, False):
        assert ide_handlers_build._truthy(value) == as_bool(value), value


def test_no_module_keeps_a_private_spelling_of_the_true_set():
    """A new `in ("1", "true", ...)` list means the divergence is growing back."""
    import re

    pattern = re.compile(r'"1"\s*,\s*"true"')
    offenders = []
    for path in (ROOT / "products").rglob("*.py"):
        if "__pycache__" in path.parts or "build" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append("{0}:{1}".format(path.relative_to(ROOT), number))
    assert offenders == []
