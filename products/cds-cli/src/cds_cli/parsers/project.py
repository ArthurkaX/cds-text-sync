"""Argument registration for project and POU commands."""

import argparse


def register(subparsers):
    project = subparsers.add_parser(
        "project",
        help=argparse.SUPPRESS,
        description="Project command interface via Project_daemon.py reverse-pipe mode.",
    )
    project.add_argument(
        "project_action",
        choices=["info", "tree", "read", "open", "close", "list", "snapshot", "build", "list-devices", "compare", "device-status", "connect", "disconnect", "read-var", "write-var", "simulate", "set-credentials", "application-state", "diagnose-online"],
        help="info - project details\n" "tree - object tree\n" "read - read object source\n" "open - open a project\n" "close - close current project\n" "list - list open projects\n" "snapshot - export full XML snapshot\n" "build - build project\n" "list-devices - list devices\n" "compare - compare with snapshot\n" "device-status - get device status\n" "connect - connect to PLC\n" "disconnect - disconnect from PLC\n" "read-var - read PLC variable\n" "write-var - write PLC variable\n" "simulate on|off - toggle simulation mode\n" "set-credentials - set PLC credentials\n" "application-state - get online application state\n",
    )
    project.add_argument("--path", default="", help="Object path (for read) or project path (for open) or output (for snapshot)")
    project.add_argument("--name", default="", help="Object name (for read) or variable name (for read-var, write-var)")
    project.add_argument("--enable", default="on", help="Enable/disable simulation (on|off, for simulate)")
    project.add_argument("--guid", default="", help="Object GUID (for read)")
    project.add_argument("--depth", type=int, default=0, help="Tree depth, 0 = unlimited")
    project.add_argument("--against", default="", help="Path to snapshot for compare")
    project.add_argument("--device", default="", help="Device name filter (for device-status)")
    project.add_argument("--ip", default="", help="PLC IP address (for connect)")
    project.add_argument("--gateway", default="Gateway-1", help="Gateway name (for connect, default: Gateway-1)")
    project.add_argument("--value", default=None, help="Value to write (for write-var)")
    project.add_argument("--username", default="", help="Username (for set-credentials)")
    project.add_argument("--password", default="", help="Password (for set-credentials)")

    pou = subparsers.add_parser(
        "pou",
        help=argparse.SUPPRESS,
        description="Delete Program Organization Units, Functions, and Function Blocks from the project.",
    )
    pou.add_argument("pou_action", choices=["delete"], help="delete - delete an object")
    pou.add_argument("name", help="Object name (e.g. MAIN, MyFunction, Globals, MyDataType)")
    pou.add_argument("--app", default="", help="Application name (default: active application)")


__all__ = ["register"]
