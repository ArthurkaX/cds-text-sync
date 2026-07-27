# -*- coding: utf-8 -*-
"""
_cli_handlers_visu.py - `cts visu ...` subcommand dispatch.

Covers the visu subcommands: types, new, create-screen, add, list,
check, describe, from-svg, to-svg, capture-frame. Extracted verbatim
from the main() dispatcher to match the _cli_handlers_project and
_cli_handlers_vars handler modules.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cli._cli_handlers_vars import _resolve_project_view
from cli._cli_io import _print_error

_SCRIPT_DIR = Path(__file__).resolve().parent


def _optional_project_view(sync_folder):
    """project-view dir if one can be found, else ``None``.

    ``preview`` and ``lint`` work on a sketch file, not on a project. They only
    want the project-view directory so an optional project-level ``visu.css``
    is picked up -- so a missing daemon or sync folder must not stop them.
    """
    try:
        pv, _ = _resolve_project_view(sync_folder)
    except SystemExit:
        return None
    return pv


def dispatch_visu(args):
    """Route a parsed `visu` subcommand to cli.visu.commands."""
    _root_dir = _SCRIPT_DIR.parent
    if str(_root_dir) not in sys.path:
        sys.path.insert(0, str(_root_dir))
    from cli.visu import commands as visu_cmds

    sync_folder = getattr(args, "sync_folder", "")
    scheme = getattr(args, "scheme", "") or None

    if args.visu_action == "types":
        visu_cmds.list_types()
        return

    if args.visu_action == "new":
        out = getattr(args, "out", "") or (
            (args.name or "screen").strip().replace(" ", "_") + ".svg"
        )
        visu_cmds.new_svg(
            out_path=out,
            name=args.name,
            width=getattr(args, "w", None) or args.width,
            height=getattr(args, "h", None) or args.height,
            scheme=scheme,
        )
        return

    if args.visu_action in ("preview", "lint"):
        if not args.svg:
            _print_error("--svg is required")
            sys.exit(1)
        background = getattr(args, "background", "") or None
        if args.visu_action == "preview":
            visu_cmds.preview_svg(
                project_view_dir=_optional_project_view(sync_folder),
                svg_path=args.svg,
                theme_name=getattr(args, "theme", "flat-style"),
                out_path=getattr(args, "out", ""),
                background=background,
                grid=getattr(args, "grid", 0) or 0,
                png=not getattr(args, "no_png", False),
                scheme=scheme,
            )
        else:
            visu_cmds.lint_svg(
                project_view_dir=_optional_project_view(sync_folder),
                svg_path=args.svg,
                theme_name=getattr(args, "theme", "flat-style"),
                background=background,
                fix=getattr(args, "fix", False),
                strict=getattr(args, "strict", False),
                scheme=scheme,
            )
        return

    pv, _ = _resolve_project_view(sync_folder)

    if args.visu_action == "create-screen":
        if not args.name:
            _print_error("--name is required")
            sys.exit(1)
        visu_cmds.create_screen(
            project_view_dir=pv,
            name=args.name,
            folder=getattr(args, "folder", ""),
            width=args.width,
            height=args.height,
            start_visu=getattr(args, "start_visu", False),
        )
    elif args.visu_action == "add":
        if not args.screen:
            _print_error("--screen is required")
            sys.exit(1)
        if not args.type:
            _print_error("--type is required")
            sys.exit(1)
        params = {}
        _visu_map = {
            "x": "x",
            "y": "y",
            "w": "width",
            "h": "height",
            "shape": "shape",
            "fill": "fill",
            "frame": "frame",
            "corner_radius": "corner_radius",
            "border_width": "border_width",
            "angle": "angle",
            "tooltip": "tooltip",
        }
        for cli_key, params_key in _visu_map.items():
            raw = getattr(args, cli_key, None)
            if raw is not None and raw != "":
                params[params_key] = raw
        visu_cmds.add_element(
            project_view_dir=pv,
            screen=args.screen,
            folder=getattr(args, "folder", ""),
            type_name=args.type,
            params=params,
        )
    elif args.visu_action == "list":
        if not args.screen:
            _print_error("--screen is required")
            sys.exit(1)
        visu_cmds.list_screen(
            project_view_dir=pv,
            screen=args.screen,
            folder=getattr(args, "folder", ""),
        )
    elif args.visu_action == "check":
        if not args.screen:
            _print_error("--screen is required")
            sys.exit(1)
        visu_cmds.check_screen(
            project_view_dir=pv,
            screen=args.screen,
            folder=getattr(args, "folder", ""),
        )
    elif args.visu_action == "describe":
        if not args.type:
            _print_error("--type is required")
            sys.exit(1)
        visu_cmds.describe(
            project_view_dir=pv,
            type_name=args.type,
            screen=getattr(args, "screen", ""),
            folder=getattr(args, "folder", ""),
            elem=getattr(args, "elem", None),
        )
    elif args.visu_action == "from-svg":
        if not args.svg:
            _print_error("--svg is required")
            sys.exit(1)
        visu_cmds.from_svg(
            project_view_dir=pv,
            svg_path=args.svg,
            screen=args.screen,
            folder=getattr(args, "folder", ""),
            theme_name=getattr(args, "theme", "flat-style"),
            out_path=getattr(args, "out", ""),
            create_screen=getattr(args, "create_screen", False),
            screen_name=getattr(args, "screen_name", ""),
            gvl_name=getattr(args, "gvl", None) or None,
            gvl_file=getattr(args, "gvl_file", None) or None,
            background=getattr(args, "background", "") or None,
            preview=not getattr(args, "no_preview", False),
            strict=getattr(args, "strict", False),
            scheme=scheme,
        )
    elif args.visu_action == "to-svg":
        if not args.screen:
            _print_error("--screen is required")
            sys.exit(1)
        visu_cmds.to_svg(
            project_view_dir=pv,
            screen=args.screen,
            folder=getattr(args, "folder", ""),
            out_path=getattr(args, "out", ""),
        )
    elif args.visu_action == "capture-frame":
        visu_name = getattr(args, "visu", "")
        if not visu_name:
            _print_error("--visu is required")
            sys.exit(1)
        visu_cmds.capture_frame(
            project_view_dir=pv,
            visu_name=visu_name,
            screen=getattr(args, "screen", None) or "",
            folder=getattr(args, "folder", ""),
        )
