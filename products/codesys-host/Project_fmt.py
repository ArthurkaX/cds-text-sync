# -*- coding: utf-8 -*-
"""Project_fmt.py - Preview and apply local ST formatting in CODESYS."""
from cds_bootstrap import launch

_ENTRY = launch("Project_fmt", script_file=__file__, caller_globals=globals())


def main(params=None):
    return _ENTRY(params=params)


if __name__ == "__main__":
    main()
