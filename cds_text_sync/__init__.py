"""Source-checkout compatibility shim for the relocated sync product.

The implementation lives in ``products/cds-text-sync/src``.  Keeping this
small package at the repository root preserves historical imports while the
repository finishes migrating callers and deployment tooling.
"""

from pathlib import Path
import sys


_PACKAGE_DIR = (
    Path(__file__).resolve().parent.parent
    / "products"
    / "cds-text-sync"
    / "src"
    / "cds_text_sync"
)

if not _PACKAGE_DIR.is_dir():
    raise ImportError(f"relocated cds_text_sync package is missing: {_PACKAGE_DIR}")

__path__ = [str(_PACKAGE_DIR)]

_REPO_ROOT = _PACKAGE_DIR.parents[3]
for _product in ("cds-static-analyzer", "cds-cli", "visu-lint"):
    _source = _REPO_ROOT / "products" / _product / "src"
    if _source.is_dir() and str(_source) not in sys.path:
        sys.path.insert(0, str(_source))

__version__ = "3.1.0"
