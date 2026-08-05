# -*- coding: utf-8 -*-
"""
Project_export.py - User entrypoint for extracting an XML dump from CODESYS.
"""
from cds_bootstrap import launch

_ENTRY = launch("Project_export", script_file=__file__, caller_globals=globals())


def main(params=None):
    return _ENTRY(params=params)


if __name__ == "__main__":
    main()
