"""Path setup for CLI product tests."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
for path in (
    ROOT / "products" / "cds-cli" / "src",
    ROOT / "products" / "cds-static-analyzer" / "src",
    ROOT / "products" / "cds-text-sync" / "src",
    ROOT / "tests" / "unit",
):
    path = str(path)
    if path not in sys.path:
        sys.path.insert(0, path)

