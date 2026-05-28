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

import sys
import os
import time


def _notify(msg, is_error=False):
    """Show a message to the user in CODESYS."""
    try:
        if is_error:
            system.ui.error(msg)
        else:
            system.ui.info(msg)
    except Exception:
        print(msg)


def main():
    # Find the reverse-pipe loop module
    script_dir = os.path.dirname(os.path.abspath(__file__))
    loop_path = os.path.join(script_dir, "src", "ide_bridge", "ide_reverse_pipe_loop.py")

    if not os.path.exists(loop_path):
        loop_path = os.path.join(script_dir, "ide_reverse_pipe_loop.py")

    if not os.path.exists(loop_path):
        _notify("ide_reverse_pipe_loop.py not found at:\n" + loop_path, is_error=True)
        return

    # Read the loop module code
    with open(loop_path, "r") as f:
        code = f.read()

    # Create namespace with current CODESYS globals
    ns = globals().copy()
    ns["__file__"] = loop_path
    ns["__name__"] = "__main__"

    try:
        exec(code, ns)
    except Exception as e:
        _notify("Reverse pipe daemon error:\n" + str(e), is_error=True)
        return

    # The loop module should have set up sys._codesys_daemon_loop
    loop_info = getattr(sys, "_codesys_daemon_loop", None)
    if not loop_info or not loop_info.get("started"):
        _notify("Reverse pipe daemon failed to start.", is_error=True)
        return

    # Keep the script context alive while daemon is running
    # When user clicks Stop, running=False and this exits naturally
    try:
        while sys._codesys_daemon_loop.get("running", False):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
