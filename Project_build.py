# -*- coding: utf-8 -*-
"""
Project_build.py - User entrypoint for building the active CODESYS application.
"""
from cds_bootstrap import launch

_ENTRY = launch("Project_build", script_file=__file__, caller_globals=globals())


def main(params=None):
    return _ENTRY(params=params)


if __name__ == "__main__":
    main()
