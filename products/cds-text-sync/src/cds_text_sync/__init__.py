"""Shared package bootstrap for the source checkout and installed wheel."""

from pathlib import Path
import sys


# The analyzer is a product with its own source root. During a source
# checkout, make that root importable before the CLI lazily imports it.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHARED_SRC = _REPO_ROOT / "shared" / "src"
if _SHARED_SRC.is_dir() and str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))
_ANALYZER_SRC = _REPO_ROOT / "products" / "cds-static-analyzer" / "src"
if _ANALYZER_SRC.is_dir() and str(_ANALYZER_SRC) not in sys.path:
    sys.path.insert(0, str(_ANALYZER_SRC))

_CLI_SRC = _REPO_ROOT / "products" / "cds-cli" / "src"
if _CLI_SRC.is_dir() and str(_CLI_SRC) not in sys.path:
    sys.path.insert(0, str(_CLI_SRC))

_VISU_LINT_SRC = _REPO_ROOT / "products" / "visu-lint" / "src"
if _VISU_LINT_SRC.is_dir() and str(_VISU_LINT_SRC) not in sys.path:
    sys.path.insert(0, str(_VISU_LINT_SRC))

__version__ = "3.1.0"
