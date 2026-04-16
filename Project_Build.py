# -*- coding: utf-8 -*-
"""
Project_Build.py - User entrypoint for building the active CODESYS application.
"""
from Project_bootstrap import run_project_command


def main(params=None):
    return run_project_command("build", params=params, script_file=__file__, caller_globals=globals())


if __name__ == "__main__":
    main()
