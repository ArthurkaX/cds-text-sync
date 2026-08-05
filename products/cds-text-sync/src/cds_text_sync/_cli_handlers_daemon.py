"""Compatibility wrapper for the daemon dispatcher moved to :mod:`cds_cli`."""

import sys

from cds_cli import _cli_handlers_daemon as _impl

sys.modules[__name__] = _impl
