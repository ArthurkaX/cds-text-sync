"""
cds_text_sync.analyze - project static analysis for exported project-view.

``cts analyze`` works only on the exported ``project-view/`` tree; it never
talks to the daemon and never reads ``.dump/``. See static_analyze/imp_plan.md
for the delivery plan this package implements.
"""

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.model import (
    AnalysisResult,
    Diagnostic,
    Finding,
    Location,
)
from cds_text_sync.analyze.project import ProjectSnapshot, Unit, build_snapshot
from cds_text_sync.analyze.workspace import Workspace, WorkspaceResolver

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
