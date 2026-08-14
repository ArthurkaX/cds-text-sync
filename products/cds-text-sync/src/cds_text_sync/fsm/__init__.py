"""FSM core package: workspace access, analysis, and JSON-safe models.

CPython 3.11 only - the CODESYS host never imports this package.  The modules
here keep their dependencies narrow: ``workspace.py`` reads the exported
``project-view`` tree and the ``.dump`` manifest, ``analyzer.py`` parses
Structured Text through the shared parser, ``model.py`` is the single
definition of the machine and file payload shapes, and ``render.py`` turns a
machine payload into layout geometry, a safe standalone SVG, and mermaid text.
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
from .render import layout_payload, to_svg, to_mermaid_text

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
    "layout_payload",
    "to_svg",
    "to_mermaid_text",
]
