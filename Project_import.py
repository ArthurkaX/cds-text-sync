# -*- coding: utf-8 -*-
"""
Project_import.py - User entrypoint for importing disk changes into CODESYS.
"""
from Project_bootstrap import run_project_command


def main(params=None):
    return run_project_command("import", params=params, script_file=__file__, caller_globals=globals())


if __name__ == "__main__":
    main()
