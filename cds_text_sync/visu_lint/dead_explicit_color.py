"""Compatibility alias for :mod:`visu_lint.dead_explicit_color`."""

import sys

from visu_lint import dead_explicit_color as _impl

sys.modules[__name__] = _impl
