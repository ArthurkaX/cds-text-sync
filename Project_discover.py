# -*- coding: utf-8 -*-
"""
Project_discover.py - User entrypoint for CODESYS environment/profile discovery.
"""
from cds_bootstrap import run_project_command


def main(params=None):
    return run_project_command("discover", params=params, script_file=__file__, caller_globals=globals())


if __name__ == "__main__":
    main()
