# -*- coding: utf-8 -*-
"""Project_fsm.py - Show the FSM transition map for a selected object."""
from cds_bootstrap import launch

_ENTRY = launch("Project_fsm", script_file=__file__, caller_globals=globals())


def main(params=None):
    return _ENTRY(params=params)


if __name__ == "__main__":
    main()
