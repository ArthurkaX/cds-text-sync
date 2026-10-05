"""The workspace fingerprint ``cts verify`` hands to the IDE daemon.

The scan itself lives with the engine, in
``cds_text_sync.engine._workspace_fingerprint``, because the daemon inside
CODESYS has to produce the identical digest from the identical files: this
module is the name the gate and its tests use, not a second implementation.

It is re-exported rather than imported directly by ``stages`` so the stage can
be tested against a scripted scan without touching the filesystem.
"""

from cds_text_sync.engine._workspace_fingerprint import (  # noqa: F401
    workspace_fingerprint,
)

__all__ = ["workspace_fingerprint"]
