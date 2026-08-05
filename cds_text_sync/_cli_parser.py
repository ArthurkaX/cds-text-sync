"""Compatibility wrapper for the CLI parser moved to :mod:`cds_cli`."""

import sys

from cds_cli import _cli_parser as _impl

sys.modules[__name__] = _impl
