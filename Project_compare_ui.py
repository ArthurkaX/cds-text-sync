# -*- coding: utf-8 -*-
"""
Project_compare_ui.py - Interactive compare entrypoint for CODESYS projects.
"""
from cds_bootstrap import launch

_ENTRY = launch("Project_compare_ui", script_file=__file__, caller_globals=globals())


def main(params=None):
    return _ENTRY(params=params)


if __name__ == "__main__":
    main()
