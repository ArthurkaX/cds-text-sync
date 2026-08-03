"""
capabilities.py - Declared data dependencies of rules.

A rule declares which views of the project it needs (``requires``) and at
which granularity it runs (``scope``). The runner checks availability and
turns an unavailable capability into a Diagnostic for the affected rules
instead of a silent "clean" result.

These capabilities are deliberately not numeric tiers: a visu-XML rule is not
a "lower tier" of the ST parser, it simply needs a different view.
"""

from __future__ import annotations

import enum


class Capability(str, enum.Enum):
    ST_TEXT = "st-text"  # raw .st text of a unit (always available)
    DECLARATIONS = "declarations"  # parsed VAR_* blocks of a unit
    PROJECT_SYMBOLS = "project-symbols"  # cross-file symbol table
    BLOCK_STRUCTURE = "block-structure"  # control-flow nesting tree of a unit
    VISU_XML = "visu-xml"  # native visu screen XML in project-view
    TEXT_LISTS = "text-lists"  # GlobalTextList XML/CSV
    TASK_CONFIG = "task-config"  # task configuration projection

    def __str__(self):  # pragma: no cover - cosmetic
        return self.value


class Scope(str, enum.Enum):
    UNIT = "unit"  # rule runs per unit; cacheable
    PROJECT = "project"  # rule needs the whole snapshot once

    def __str__(self):  # pragma: no cover - cosmetic
        return self.value


class CapabilityError(Exception):
    """A declared capability could not be provided for this run.

    Raised by a capability provider; the runner converts it into a
    Diagnostic and marks the run incomplete (policy-controlled).
    """

    def __init__(self, capability, message):
        super().__init__(message)
        self.capability = capability
        self.message = message
