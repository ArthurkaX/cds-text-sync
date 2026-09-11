"""Argument registration for documentation generation."""


def register(subparsers):
    parser = subparsers.add_parser("docs", help="Generate LLM-friendly project and library documentation")
    parser.add_argument("--workspace", default="", help="Sync folder or project-view/ (default: current directory)")
    parser.add_argument(
        "--libraries", "--library-path", dest="library_path", default="",
        help=r"CODESYS library root (default: C:\ProgramData\CODESYS)",
    )
    parser.add_argument("--output", "--out", dest="output", default="", help="Documentation output directory")
    parser.add_argument("--daemon", action="store_true", help="Generate through the running CODESYS daemon")
    parser.add_argument("--timeout", type=float, default=120, help="Daemon timeout in seconds (default: 120)")


__all__ = ["register"]
