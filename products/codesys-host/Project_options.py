# -*- coding: utf-8 -*-
"""
Project_options.py - User entrypoint for project sync options.
"""
from cds_bootstrap import launch

_ENTRY = launch("Project_options", script_file=__file__, caller_globals=globals())


def main(params=None):
    return _ENTRY(params=params)


if __name__ == "__main__":
    main()
