"""Compatibility wrapper for variable handlers moved to :mod:`cds_cli`."""

import sys

from cds_cli import _cli_handlers_vars as _impl

sys.modules[__name__] = _impl
