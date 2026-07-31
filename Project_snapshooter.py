# -*- coding: utf-8 -*-
"""
Project_snapshooter.py - CODESYS entrypoint for PLC variable presets.

Usage in CODESYS scripting:

    import Project_snapshooter as snapshooter
    data = snapshooter.take(paths=["GVL_Routing.partCount"], label="speed")
    report = snapshooter.restore(data, apply=False)

Run the script directly to start the small interactive wizard.
"""

from __future__ import print_function

from cds_bootstrap import launch

_ENTRY = launch("Project_snapshooter", script_file=__file__, caller_globals=globals())


def main(params=None):
    return _ENTRY(params=params)


if __name__ == "__main__":
    main()
