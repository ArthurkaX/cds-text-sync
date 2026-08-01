"""
json.py - Versioned JSON envelope for ``cts analyze``.

Machine output goes to stdout, service messages to stderr. The envelope is
stable: schema_version, complete, findings, diagnostics, summary.
"""

from __future__ import annotations

import json


def render(result):
    """Render an AnalysisResult as the versioned JSON document."""
    return (
        json.dumps(
            result.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )
