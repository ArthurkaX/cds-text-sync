"""Argument registration for the patch commands."""


def register(subparsers):
    parser = subparsers.add_parser(
        "patch",
        help="Package changed text files for a colleague",
        description=(
            "Hand over the text you changed on disk. Runs a compare against the "
            "live IDE and copies only the changed .st, .csv and visualization "
            "files into a folder that mirrors the project structure."
        ),
        epilog="""
Subcommands:
  cts patch save                     write the patch to .dump/patch/patch_<UTC>
  cts patch save --out D:\\share\\fix  write it somewhere else
  cts patch save --zip               also produce <folder>.zip
  cts patch save --dry-run           list what would be packaged

On the receiving side: copy project-view/ from the patch over your own sync
folder root, replacing files, then run 'cts compare' and 'cts import'.
""",
    )
    nested = parser.add_subparsers(dest="patch_action", metavar="SUBCOMMAND")

    save = nested.add_parser(
        "save",
        help="Compare against the IDE and write the changed text files",
    )
    save.add_argument(
        "--out",
        default="",
        help="Output folder (default: <sync folder>/.dump/patch/patch_<UTC timestamp>)",
    )
    save.add_argument(
        "--sync-folder",
        dest="sync_folder",
        default="",
        help="Sync folder to use instead of asking the daemon",
    )
    save.add_argument(
        "--zip",
        action="store_true",
        help="Also write <output folder>.zip",
    )
    save.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="List what would be packaged without writing anything",
    )
    save.add_argument(
        "--bare",
        action="store_true",
        help="Write only the files, without patch.json and README.txt",
    )
    save.add_argument(
        "--timeout",
        type=float,
        default=120,
        help="Timeout in seconds waiting for the IDE compare (default: 120)",
    )


__all__ = ["register"]
