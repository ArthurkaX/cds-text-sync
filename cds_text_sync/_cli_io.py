"""Compatibility wrapper for CLI I/O moved to :mod:`cds_cli`."""

import sys

from cds_cli import _cli_io as _impl

sys.modules[__name__] = _impl
