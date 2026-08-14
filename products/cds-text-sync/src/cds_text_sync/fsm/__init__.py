"""FSM core package: workspace access, analysis, and JSON-safe models.

CPython 3.11 only - the CODESYS host never imports this package.  The modules
here keep their dependencies narrow: ``workspace.py`` reads the exported
``project-view`` tree and the ``.dump`` manifest, ``analyzer.py`` parses
Structured Text through the shared parser, and ``model.py`` is the single
definition of the machine and file payload shapes.
"""

from .model import (
    machine_payload,
    file_result,
    machine_from_payload,
    STATE_FSM,
    STATE_NONE,
    STATE_ERROR,
)
from .workspace import source_root, bootstrap
from .analyzer import analyze_text, analyze_path

__all__ = [
    "machine_payload",
    "file_result",
    "machine_from_payload",
    "STATE_FSM",
    "STATE_NONE",
    "STATE_ERROR",
    "source_root",
    "bootstrap",
    "analyze_text",
    "analyze_path",
]
