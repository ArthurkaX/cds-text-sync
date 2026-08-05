"""Bootstrap for sync-product compatibility tests."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for source in (
    ROOT / "src",
    ROOT.parent / "cds-static-analyzer" / "src",
):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
