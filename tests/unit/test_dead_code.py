"""No Python function, method, class, variable or import that nothing uses.

vulture reads the sources; what it cannot see used is reached by name from
outside Python or kept on purpose, and is listed below with the reason.
Unused attributes are not checked: most are .NET properties the IronPython
host sets on IDE objects.  Skipped where vulture (requirements-dev.txt) is not
installed.
"""

import os

import pytest

vulture = pytest.importorskip("vulture")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

USED_ELSEWHERE: set[str] = set()


def test_no_unused_code():
    scanner = vulture.Vulture()
    # Every Python file that ships or runs, tests aside: the CODESYS host's
    # headless runner and the repository tools.
    scanner.scavenge([os.path.join(ROOT, path) for path in ("products/codesys-host/headless", "tools")])
    unused = [
        "{0}:{1}: unused {2} '{3}'".format(
            os.path.relpath(str(item.filename), ROOT), item.first_lineno, item.typ, item.name)
        for item in scanner.get_unused_code(min_confidence=60)
        if item.typ != "attribute" and item.name not in USED_ELSEWHERE
    ]
    assert not unused, "delete it, or say in USED_ELSEWHERE who uses it:\n" + "\n".join(unused)
