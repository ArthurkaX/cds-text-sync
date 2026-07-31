# -*- coding: utf-8 -*-
"""
Project_resources.py - User entrypoint for snapshot-based resource diagnostics.
"""
from cds_bootstrap import launch

_ENTRY = launch("Project_resources", script_file=__file__, caller_globals=globals())


def main(params=None):
    return _ENTRY(params=params)


if __name__ == "__main__":
    main()
