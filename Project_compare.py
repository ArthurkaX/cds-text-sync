# -*- coding: utf-8 -*-
"""
Project_compare.py - User entrypoint for comparing CODESYS state with disk files.
"""
from Project_bootstrap import run_project_command


def main(params=None):
    return run_project_command("compare", params=params, script_file=__file__, caller_globals=globals())


if __name__ == "__main__":
    main()
