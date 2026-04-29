# -*- coding: utf-8 -*-
"""
Project_resources.py - User entrypoint for snapshot-based resource diagnostics.
"""
from cds_bootstrap import run_project_command


def main(params=None):
    return run_project_command("resources", params=params, script_file=__file__, caller_globals=globals())


if __name__ == "__main__":
    main()
