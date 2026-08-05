"""
cds_static_analyzer - project static analysis for exported project-view.

``cts analyze`` works only on the Structured Text (``.st``) objects exported
into ``project-view/``; it never talks to the daemon and never reads
``.dump/``. Visualization XML belongs to the separate ``cts visu-lint``
machine-feedback tool and is not part of the analyzer rule contract. The
repository-level product plan lives in ``spec.md``.
"""

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.model import (
    AnalysisResult,
    Diagnostic,
    Finding,
    Location,
)
from cds_static_analyzer.project import ProjectSnapshot, Unit, build_snapshot
from cds_static_analyzer.workspace import Workspace, WorkspaceResolver

__all__ = [
    "AnalysisResult",
    "Capability",
    "Diagnostic",
    "Finding",
    "Location",
    "ProjectSnapshot",
    "Scope",
    "Unit",
    "Workspace",
    "WorkspaceResolver",
    "build_snapshot",
]
