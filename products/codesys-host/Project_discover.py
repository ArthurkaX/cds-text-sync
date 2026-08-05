# -*- coding: utf-8 -*-
"""
Project_discover.py - User entrypoint for CODESYS environment/profile discovery.
"""
from cds_bootstrap import launch

_ENTRY = launch("Project_discover", script_file=__file__, caller_globals=globals())


def main(params=None):
    return _ENTRY(params=params)


if __name__ == "__main__":
    main()
