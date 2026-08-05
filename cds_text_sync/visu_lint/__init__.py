"""Compatibility package for the product now provided by :mod:`visu_lint`."""

import sys

from visu_lint import __name__ as _name  # noqa: F401

__path__ = []
sys.modules[__name__] = sys.modules["visu_lint"]
