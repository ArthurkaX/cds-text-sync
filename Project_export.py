# -*- coding: utf-8 -*-
"""
Project_export.py - User entrypoint for exporting the active CODESYS project.
"""
from cds_bootstrap import run_project_command


def main(params=None):
    return run_project_command("export", params=params, script_file=__file__, caller_globals=globals())


if __name__ == "__main__":
    main()
