# -*- coding: utf-8 -*-
"""Project_analyze_ui.py - Open offline static analysis for this project."""
from cds_bootstrap import launch

_ENTRY = launch("Project_analyze_ui", script_file=__file__, caller_globals=globals())


def main(params=None):
    return _ENTRY(params=params)


if __name__ == "__main__":
    main()
