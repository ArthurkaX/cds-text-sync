# -*- coding: utf-8 -*-
"""Classify a CODESYS build-message severity, whatever its casing.

CODESYS spells the severity itself, and the casing is not part of any
contract: the daemon used to test ``"Error" in severity`` and the CLI did the
same, so an IDE that answers ``error``/``ERROR``/``Error:`` made the compiler's
verdict depend on a capital letter -- a real compile failure reported as a
clean build, or the reverse.  Both sides now ask this one function, so the
counts they publish and the problems the CLI derives cannot disagree.

IronPython 2.7 compatible: no annotations, no f-strings.
"""

from __future__ import print_function

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

#: Checked in this order: "Compile Error" must not be read as a warning.
_KINDS = (
    (SEVERITY_ERROR, "error"),
    (SEVERITY_WARNING, "warning"),
    (SEVERITY_INFO, "info"),
)


def severity_kind(value):
    """The kind of a CODESYS severity string, or ``""`` when unrecognised.

    A substring test on the lowered text, because CODESYS qualifies the word
    itself ("Error", "Compile Error", "Warning").  Anything else -- including
    a value this function has never seen -- is ``""``: unknown is not an
    error, it is evidence the caller does not have.
    """
    text = str(value).strip().lower() if value is not None else ""
    for kind, needle in _KINDS:
        if needle in text:
            return kind
    return ""
