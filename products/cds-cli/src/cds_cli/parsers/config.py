"""Argument registration for ``cts config`` (offline settings layers)."""


def register(subparsers):
    parser = subparsers.add_parser(
        "config",
        help="Show or change settings: code defaults, per-user defaults, project file",
        description=(
            "Inspect and edit the three settings layers without a daemon: the "
            "code defaults, the per-user defaults.json, and the project's "
            "cds-text-sync.json. `show` reports the effective value and where "
            "each one came from; `set`/`unset` change one layer."
        ),
    )
    actions = parser.add_subparsers(
        dest="config_action",
        required=True,
        metavar="action",
    )

    show = actions.add_parser(
        "show",
        help="Show the effective settings and the source of each value",
    )
    show.add_argument(
        "--project-root",
        default="",
        help=(
            "Sync folder to read (default: nearest cds-text-sync.json found "
            "from the current directory upward)"
        ),
    )
    # Own dest: the global --output/--pretty select the format for the daemon
    # commands, and this command's default is the table, not JSON.
    show.add_argument(
        "--json",
        dest="config_json",
        action="store_true",
        help="Emit machine-readable JSON instead of the table",
    )

    for action, help_text in (
        ("set", "Change one setting in the user (default) or project layer"),
        ("unset", "Remove one setting from the user (default) or project layer"),
    ):
        sub = actions.add_parser(action, help=help_text)
        sub.add_argument(
            "key", help="Setting name; `cts config show` prints the valid ones"
        )
        if action == "set":
            sub.add_argument(
                "value",
                help="New value: parsed as JSON when possible (true, 10, [..]), else a raw string",
            )
        layer = sub.add_mutually_exclusive_group()
        layer.add_argument(
            "--user",
            dest="config_layer",
            action="store_const",
            const="user",
            default="user",
            help="Edit the per-user defaults.json (default)",
        )
        layer.add_argument(
            "--project",
            dest="config_layer",
            action="store_const",
            const="project",
            help="Edit the project's cds-text-sync.json (must already exist)",
        )
        sub.add_argument(
            "--project-root",
            default="",
            help=(
                "Sync folder to edit (default: nearest cds-text-sync.json found "
                "from the current directory upward)"
            ),
        )


__all__ = ["register"]
