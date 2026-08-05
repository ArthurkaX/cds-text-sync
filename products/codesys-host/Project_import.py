# -*- coding: utf-8 -*-
"""
Project_import.py - User entrypoint for injecting XML patches into CODESYS.
"""
from cds_bootstrap import launch

_ENTRY = launch("Project_import", script_file=__file__, caller_globals=globals())


def main(params=None):
    return _ENTRY(params=params)


if __name__ == "__main__":
    main()
