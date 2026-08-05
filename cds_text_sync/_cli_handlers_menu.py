"""Compatibility wrapper for the menu dispatcher moved to :mod:`cds_cli`."""

import sys

from cds_cli import _cli_handlers_menu as _impl

sys.modules[__name__] = _impl
