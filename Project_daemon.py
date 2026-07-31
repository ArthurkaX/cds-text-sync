# -*- coding: utf-8 -*-
"""
Project_daemon.py — Reverse-pipe daemon launcher.

This is the CODESYS-side entry point.
It runs the main loop that polls for CLI commands and executes them
in the same script context (no background thread).

Architecture:
  CLI creates a named pipe server -> CODESYS polls as client

Usage in CODESYS:
    Tools -> Scripting -> Execute Script -> Project_daemon.py
"""
from cds_bootstrap import launch

_ENTRY = launch("Project_daemon", script_file=__file__, caller_globals=globals())


def main(params=None):
    return _ENTRY(params=params)


if __name__ == "__main__":
    main()
