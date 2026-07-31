# -*- coding: utf-8 -*-
"""
Project_directory.py - User entrypoint for setting the sync directory.
"""
from cds_bootstrap import launch

_ENTRY = launch("Project_directory", script_file=__file__, caller_globals=globals())


def main(params=None):
    return _ENTRY(params=params)


set_base_directory = main


if __name__ == "__main__":
    main()
