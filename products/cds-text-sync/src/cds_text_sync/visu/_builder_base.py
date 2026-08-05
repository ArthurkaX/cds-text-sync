# -*- coding: utf-8 -*-
"""
_builder_base.py - Shared primitives for the visu builder package.

Holds the leaf-level constants, the BuilderError exception, and the XML-escape
helper that every builder submodule needs. Keeping them here lets builder.py and
its per-capability submodules (e.g. builder_inputs) depend on a common base
without importing each other, so there is no circular import.

BuilderError and _esc remain the public surface via `builder.BuilderError` /
`builder._esc`, which re-export from here.
"""

from __future__ import print_function

# Member block element type guid (every VisualElemMemberList entry).
_MEMBER_TYPE = "{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}"
_COLOR_TYPE = "{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}"
_FONT_TYPE = "{9e842eb2-1463-4af2-b605-4fbb17044f94}"
_ROOT_TYPE = "{6198ad31-4b98-445c-927f-3258a0e82fe3}"

_EL = " " * 12  # the <Single Type="{f86c2928...}"> element block indent
_MB = " " * 16  # member block indent inside VisualElemMemberList


class BuilderError(Exception):
    pass


def _esc(value):
    if value is None:
        value = ""
    value = str(value)
    value = value.replace("&", "&amp;")
    value = value.replace("<", "&lt;")
    value = value.replace(">", "&gt;")
    return value
