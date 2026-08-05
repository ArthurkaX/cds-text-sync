"""Shared package bootstrap for the source checkout and installed wheel."""

from pathlib import Path
import sys


# The analyzer is a product with its own source root. During a source
# checkout, make that root importable before the CLI lazily imports it.
_ANALYZER_SRC = (
    Path(__file__).resolve().parent.parent
    / "products"
    / "cds-static-analyzer"
    / "src"
)
if _ANALYZER_SRC.is_dir() and str(_ANALYZER_SRC) not in sys.path:
    sys.path.insert(0, str(_ANALYZER_SRC))

__version__ = "3.0.0"
