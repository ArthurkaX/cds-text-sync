"""Every test file must have exactly one owning product manifest.

`tools/ci_product_checks.py manifests` is the authority; running it from the
suite keeps a newly added test file from silently shipping unowned until
someone remembers to invoke the script by hand.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import ci_product_checks


def test_every_test_file_has_exactly_one_product_owner():
    ci_product_checks.check_manifests()  # SystemExit on duplicate or unowned
