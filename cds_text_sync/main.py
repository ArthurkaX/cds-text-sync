"""Compatibility wrapper for the CLI moved to :mod:`cds_cli`."""

from cds_cli.main import *  # noqa: F401,F403
from cds_cli.main import main

if __name__ == "__main__":
    main()
