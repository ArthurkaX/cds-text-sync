"""Compatibility alias for :mod:`visu_lint.cli`."""

import sys

from visu_lint import cli as _impl

sys.modules[__name__] = _impl
