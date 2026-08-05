"""
staleness.py - Detect a project-view that lagged behind the IDE.

``cts analyze`` works only on the exported ``project-view/`` tree and never
talks to CODESYS or the daemon. When the project moves forward inside the IDE
and nobody re-exports, the analyzer would otherwise report "clean" for code
that no longer exists. The IDE-side XML mirror in ``.dump/`` is the tell: if an
entry's ``.dump`` XML is newer than its ``.st`` projection, the IDE side moved
ahead of the text we are analysing.

The reverse - a locally edited ``.st`` newer than its XML - is the normal
text-first workflow and must never be reported: that is the state ``cts
import`` exists to push back into CODESYS, not a staleness problem.

Staleness detection is best-effort by design. A bare ``project-view/`` with no
sync state, an unreadable or malformed manifest, or a manifest pointing at
files that are not on disk are all silent no-ops: this capability must never
break or fail a run.
"""

from __future__ import annotations

import json
import os

from cds_static_analyzer.model import Diagnostic

# FAT / network-share timestamp granularity. Two files "written back to back"
# can legitimately share a timestamp; anything closer than this is treated as
# equal rather than one having moved ahead.
MTIME_TOLERANCE_SECONDS = 2.0


def stale_projections(workspace):
    """Project-view-relative projection paths whose .dump XML source is newer.

    Returns a sorted, de-duplicated list of forward-slash paths. Always
    returns ``[]`` (never raises) when there is no usable sync state.
    """
    manifest_path = os.path.join(workspace.root, ".dump", "manifest.json")
    if not os.path.isfile(manifest_path):
        return []
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception:
        return []
    if not isinstance(manifest, dict):
        return []

    stale = set()
    project_view = workspace.project_view
    for entry in manifest.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        xml_path = entry.get("xml_path") or entry.get("view_path")
        if not xml_path:
            continue
        if str(entry.get("xml_root") or "").lower() == "dump":
            xml_file = os.path.join(workspace.root, ".dump", xml_path)
        else:
            xml_file = os.path.join(project_view, xml_path)
        if not os.path.isfile(xml_file):
            continue
        try:
            xml_mtime = os.path.getmtime(xml_file)
        except OSError:
            continue
        for proj_path in entry.get("projection_paths") or []:
            proj_file = os.path.join(project_view, proj_path)
            if not os.path.isfile(proj_file):
                continue
            try:
                proj_mtime = os.path.getmtime(proj_file)
            except OSError:
                continue
            if xml_mtime - proj_mtime > MTIME_TOLERANCE_SECONDS:
                stale.add(str(proj_path).replace("\\", "/"))
    return sorted(stale)


def staleness_diagnostic(workspace):
    """A single aggregate Diagnostic, or None when the view is up to date.

    One Diagnostic for the whole stale set, not one per file: the user's
    remedy - re-export the project view - is identical no matter how many
    projections lagged, so N copies would carry no extra information. The
    message names up to three examples plus the true total.
    """
    stale = stale_projections(workspace)
    if not stale:
        return None
    count = len(stale)
    examples = ", ".join(stale[:3])
    if count == 1:
        message = (
            f"{count} project-view file is stale: {examples}. The IDE side "
            "(.dump XML) moved ahead of the text you are analysing; run "
            "'cts export' so the analysis matches the current project."
        )
    else:
        message = (
            f"{count} project-view files are stale (e.g. {examples}). The IDE "
            "side (.dump XML) moved ahead of the text you are analysing; run "
            "'cts export' so the analysis matches the current project."
        )
    return Diagnostic("project-stale", message)
