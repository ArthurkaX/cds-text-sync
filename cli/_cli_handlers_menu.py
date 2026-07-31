# -*- coding: utf-8 -*-
"""Handlers for the local, CODESYS-free menu commands.

``install-menu`` writes the Tools>Scripting stubs into ScriptDir; ``where``
reports which tree those stubs point at. Neither talks to the daemon, so they
are dispatched before any pipe connection is attempted.
"""

from __future__ import annotations

import json

from cli._cli_io import _format_output, _print_error, _print_ok
from cli.install_menu import (
    MenuError,
    describe,
    format_result,
    run_from_args,
)


def _emit(data, output_fmt, title):
    if output_fmt == "text":
        print(_format_output(data, "text", title))
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def _cmd_install_menu(args, output_fmt):
    try:
        results = run_from_args(args)
    except MenuError as error:
        _print_error(str(error))
        raise SystemExit(2)

    failed = False
    for result in results:
        if output_fmt == "text":
            print(format_result(result))
        if result["problems"]:
            failed = True

    if output_fmt != "text":
        print(json.dumps(results, indent=2, ensure_ascii=False))

    if failed:
        _print_error("the generated menu did not verify; see the problems above")
        raise SystemExit(1)

    if not getattr(args, "dry_run", False):
        _print_ok("menu written")


def _cmd_where(args, output_fmt):
    info = describe(
        body_root=getattr(args, "body", "") or None,
        script_dir=getattr(args, "script_dir", "") or None,
    )

    if output_fmt == "text":
        print("Body   : {0}".format(info["body_root"]))
        print("Valid  : {0}".format(info["body_valid"]))
        print("Layout : {0}".format(info["layout"]))
        if info["body_inside_script_dir"]:
            how = (
                "is linked from" if info.get("exposure") == "links"
                else "sits inside"
            )
            print("[WARN] the tool {0} a ScriptDir, so CODESYS scans all of it: {1}".format(
                how, info["body_inside_script_dir"]))
        for entry in info["script_dirs"]:
            print("Menu   : {0}  [{1}]".format(entry["menu_dir"], entry["layout"]))
            for problem in entry["problems"]:
                print("         [PROBLEM] {0}".format(problem))
        if not info["script_dirs"]:
            print("Menu   : no CODESYS ScriptDir found on this machine")
    else:
        _emit(info, output_fmt, "cds-text-sync")


def dispatch_menu(args, output_fmt="json"):
    """Handle a local menu command. Return True if handled, else False."""
    command = getattr(args, "command", None)

    if command == "install-menu":
        _cmd_install_menu(args, output_fmt)
        return True

    if command == "where":
        _cmd_where(args, output_fmt)
        return True

    return False
