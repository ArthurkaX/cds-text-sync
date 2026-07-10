# -*- coding: utf-8 -*-
"""
cds_text_sync.py - CLI for cds-text-sync.

Universal entry point for CODESYS project sync.
Communicates with daemon inside CODESYS via Named Pipe.

Usage:
  cds-text-sync --help
  cds-text-sync status
  cds-text-sync export|import|compare
  cds-text-sync raw <daemon-method> [--key value ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

_SCRIPT_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _SCRIPT_DIR / "external_engine"
if _ENGINE_DIR.exists() and str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

# -- Re-exports from submodules (used by main() and kept accessible) ----------

from cli._cli_io import (  # noqa: E402
    _print_error,
    _print_info,
    _print_ok,
    _format_output,
    _print_rp_error,
    _parse_key_value_args,
    _load_project_config,
    _find_codesys,
    _launch_codesys,
    _project_command,
    cmd_rp_command,
    cmd_daemon,
    cmd_direct,
    send_command_reverse,
    ENGINE_CLI,
    DAEMON_SCRIPT,
    _CODESYS_CANDIDATES,
)

from cli._cli_parser import build_parser  # noqa: E402

from cli._cli_handlers_project import (  # noqa: E402
    cmd_project_info,
    cmd_project_tree,
    cmd_project_read,
    cmd_project_open,
    cmd_project_close,
    cmd_project_list,
    cmd_project_snapshot,
    cmd_project_build,
    cmd_project_list_devices,
    cmd_device_status,
    cmd_connect,
    cmd_disconnect,
    cmd_read_var,
    cmd_write_var,
    cmd_simulate,
    cmd_set_credentials,
    cmd_application_state,
    cmd_diagnose_online,
    cmd_discover,
    cmd_compare,
    cmd_pou_delete,
)

from cli._cli_handlers_vars import (  # noqa: E402
    _resolve_project_view,
    _build_map_rows,
    _write_csv,
    cmd_read_vars,
    cmd_variable_map,
    cmd_variable_snapshot,
    cmd_variable_restore,
)

_BATCH_SIZE = 500


# -- Entry point -------------------------------------------------------------


def main():
    parser = build_parser()

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    if len(sys.argv) == 2 and ("--help" in sys.argv or "-h" in sys.argv):
        parser.print_help()
        sys.exit(0)

    args, unknown = parser.parse_known_args()

    use_reverse = True

    # Determine output format
    output_fmt = getattr(args, "output", "json")
    if getattr(args, "pretty", False):
        output_fmt = "text"

    # Deprecated direct engine aliases retained for compatibility.
    if args.command in ("validate", "resources"):
        full_args = [args.command] + unknown
        cmd_direct(full_args)
        return

    if args.command == "engine":
        if not args.engine_args:
            _print_error(
                "Specify an engine command: export, import, compare, validate, resources"
            )
            sys.exit(1)
        cmd_direct(args.engine_args)
        return

    daemon_methods = {
        "ping": "ping",
        "status": "status",
        "export": "sync_export_text",
        "import": "sync_import_text",
        "compare": "sync_compare_text",
        "build": "build",
        "disconnect": "disconnect_from_device",
        "download": "download",
        "start": "start_plc",
        "stop": "stop_plc",
        "app-state": "application_state",
        "plc-crc": "compare",
        "project-info": "project_info",
        "permissions": "permissions",
    }

    if args.command in daemon_methods:
        params = {}
        if args.command == "import":
            if getattr(args, "force_online", False):
                params["force_online"] = True
            if getattr(args, "dry_run", False):
                # Dry-run shows the same preview as compare.
                cmd_daemon(
                    "sync_compare_text",
                    {},
                    timeout=getattr(args, "timeout", 60),
                    output_fmt=output_fmt,
                )
                return
        if args.command == "download" and getattr(args, "start", None) is not None:
            params["start"] = args.start
        if args.command == "plc-crc" and getattr(args, "build", False):
            cmd_daemon("build", {}, timeout=args.timeout, output_fmt=output_fmt)
        cmd_daemon(
            daemon_methods[args.command],
            params,
            timeout=getattr(args, "timeout", 15),
            output_fmt=output_fmt,
        )
        return

    if args.command == "connect":
        params = {}
        if args.ip:
            params["ipAddress"] = args.ip
        if args.gateway:
            params["gatewayName"] = args.gateway
        cmd_daemon(
            "connect_to_device", params, timeout=args.timeout, output_fmt=output_fmt
        )
        return

    if args.command == "read":
        cmd_daemon(
            "read_variable",
            {"name": args.name},
            timeout=args.timeout,
            output_fmt=output_fmt,
        )
        return

    if args.command == "write":
        # Write and then read back so the caller can verify the value actually
        # took effect, returned in a single response.
        try:
            wr = send_command_reverse(
                "write_variable",
                {"name": args.name, "value": args.value},
                timeout=args.timeout,
            )
            if not wr.get("ok"):
                _print_rp_error(wr, "write_variable")
                sys.exit(1)
            rb = send_command_reverse(
                "read_variable", {"name": args.name}, timeout=args.timeout
            )
            read_back = rb.get("data", {}) if rb.get("ok") else {}
            print(
                _format_output(
                    {"written": True, "read_back": read_back},
                    fmt=output_fmt,
                    title="write",
                )
            )
        except RuntimeError as e:
            _print_error("Write failed: {0}".format(e))
            sys.exit(1)
        return

    if args.command == "test":
        params = {}
        if args.file:
            params["file"] = args.file
        cmd_daemon("cicd", params, timeout=args.timeout, output_fmt=output_fmt)
        return

    if args.command == "project-tree":
        cmd_daemon(
            "project_tree",
            {"depth": args.depth},
            timeout=args.timeout,
            output_fmt=output_fmt,
        )
        return

    if args.command == "read-object":
        params = {}
        if args.path:
            params["path"] = args.path
        if args.name:
            params["name"] = args.name
        if args.guid:
            params["guid"] = args.guid
        cmd_daemon("read_object", params, timeout=args.timeout, output_fmt=output_fmt)
        return

    if args.command == "update-pou":
        params = {
            "name": args.name,
            "st_path": args.st_path,
        }
        if args.app:
            params["app"] = args.app
        cmd_daemon("update_pou", params, timeout=args.timeout, output_fmt=output_fmt)
        return

    if args.command == "delete-pou":
        params = {"name": args.name}
        if args.app:
            params["app"] = args.app
        cmd_daemon("delete_pou", params, timeout=args.timeout, output_fmt=output_fmt)
        return

    if args.command == "read-log":
        params = {}
        if args.last:
            params["last"] = args.last
        if args.clear:
            params["clear"] = True
        cmd_daemon("read_log", params, timeout=args.timeout, output_fmt=output_fmt)
        return

    if args.command in ("raw", "rp"):
        cmd_rp_command(
            args.cmd_args, timeout=getattr(args, "timeout", 15), output_fmt=output_fmt
        )

    elif args.command == "project":
        if args.project_action == "info":
            cmd_project_info(use_reverse=use_reverse)
        elif args.project_action == "tree":
            cmd_project_tree(depth=args.depth, use_reverse=use_reverse)
        elif args.project_action == "read":
            cmd_project_read(
                path=args.path, name=args.name, guid=args.guid, use_reverse=use_reverse
            )
        elif args.project_action == "open":
            cmd_project_open(path=args.path, use_reverse=use_reverse)
        elif args.project_action == "close":
            cmd_project_close(use_reverse=use_reverse)
        elif args.project_action == "list":
            cmd_project_list(use_reverse=use_reverse)
        elif args.project_action == "snapshot":
            cmd_project_snapshot(path=args.path, use_reverse=use_reverse)
        elif args.project_action == "build":
            cmd_project_build(use_reverse=use_reverse)
        elif args.project_action == "list-devices":
            cmd_project_list_devices(use_reverse=use_reverse)
        elif args.project_action == "compare":
            cmd_compare(against=args.against, use_reverse=use_reverse)
        elif args.project_action == "device-status":
            cmd_device_status(device=args.device, use_reverse=use_reverse)
        elif args.project_action == "connect":
            cmd_connect(ip=args.ip, gateway=args.gateway, use_reverse=use_reverse)
        elif args.project_action == "disconnect":
            cmd_disconnect(use_reverse=use_reverse)
        elif args.project_action == "read-var":
            cmd_read_var(name=args.name, use_reverse=use_reverse)
        elif args.project_action == "write-var":
            cmd_write_var(name=args.name, value=args.value, use_reverse=use_reverse)
        elif args.project_action == "simulate":
            cmd_simulate(enable=args.enable, use_reverse=use_reverse)
        elif args.project_action == "set-credentials":
            cmd_set_credentials(
                username=args.username, password=args.password, use_reverse=use_reverse
            )
        elif args.project_action == "application-state":
            cmd_application_state(use_reverse=use_reverse)
        elif args.project_action == "diagnose-online":
            cmd_diagnose_online(use_reverse=use_reverse)

    elif args.command == "pou":
        if args.pou_action == "delete":
            cmd_pou_delete(name=args.name, app=args.app, use_reverse=use_reverse)

    elif args.command == "discover":
        cmd_discover(use_reverse=use_reverse)

    elif args.command == "read-vars":
        cmd_read_vars(
            names=args.names,
            file_path=args.file,
            timeout=args.timeout,
            output_fmt=output_fmt,
        )

    elif args.command == "variable-map":
        cmd_variable_map(
            path_filter=args.path,
            out=args.out,
            sync_folder=args.sync_folder,
            include_programs=not args.globals_only,
            output_fmt=output_fmt,
        )

    elif args.command == "variable-snapshot":
        cmd_variable_snapshot(
            path_filter=args.path,
            out=args.out,
            sync_folder=args.sync_folder,
            include_programs=not args.globals_only,
            timeout=args.timeout,
            output_fmt=output_fmt,
        )

    elif args.command == "variable-restore":
        cmd_variable_restore(
            input_path=args.input,
            report=args.report,
            path_filter=args.path,
            do_apply=args.apply,
            force=args.force,
            sync_folder=args.sync_folder,
            timeout=args.timeout,
            output_fmt=output_fmt,
        )

    elif args.command == "visu":
        _root_dir = _SCRIPT_DIR.parent
        if str(_root_dir) not in sys.path:
            sys.path.insert(0, str(_root_dir))
        from cli.visu import commands as visu_cmds

        sync_folder = getattr(args, "sync_folder", "")

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

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
