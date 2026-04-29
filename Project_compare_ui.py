# -*- coding: utf-8 -*-
"""
Project_compare_ui.py - Interactive compare entrypoint for CODESYS projects.
"""
from cds_bootstrap import run_project_command


def main(params=None):
    return run_project_command("compare_ui", params=params, script_file=__file__, caller_globals=globals())


if __name__ == "__main__":
    main()
