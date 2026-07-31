# -*- coding: utf-8 -*-
"""Generate the CODESYS Tools>Scripting menu stubs.

The CODESYS Script Engine scans its ScriptDir fully recursively and filters
only by file extension, so every ``.py`` anywhere under it lands in the menu.
Installing the whole tool there therefore pollutes the menu with ~120 internal
modules. The fix is a split install: the real tree ("the body") lives outside
ScriptDir, and ScriptDir holds nothing but the generated ``Project_*.py`` stubs
produced here -- each one pinned to the body via a ``CDS_HOME`` literal.

Deliberately stdlib-only, and deliberately free of any ``cds_text_sync`` sibling import,
so that ``python -m cds_text_sync.install_menu`` works from a fresh clone before
``pip install -e`` has run.
"""

import argparse
import glob
import importlib.util
import os
import sys
from pathlib import Path

MARKER = "# cds-text-sync generated menu stub - DO NOT EDIT"

# Frozen: users are told to pin these to their CODESYS toolbar, and the button
# binding follows the path. Renaming the folder or the files silently costs
# every existing user their buttons.
MENU_FOLDER = "cds-text-sync"

# Byte-code caches hold no .py, so CODESYS never lists them and they carry no
# user data. Clean them up quietly rather than reporting them as a problem --
# a Python 3 import of a stub (a test, a diagnostic) is enough to create one.
_DISPOSABLE_DIRS = frozenset(["__pycache__"])

_SENTINEL_DIR = Path("src") / "ide_bridge"


# -- locating things ---------------------------------------------------------


def default_body_root():
    """Where the installer puts the body when the user does not choose."""
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "cds-text-sync"
    return Path.home() / "cds-text-sync"


def body_is_valid(body):
    """True when *body* looks like a cds-text-sync tree."""
    if not body:
        return False
    body = Path(body)
    return (body / _SENTINEL_DIR).is_dir() and (body / "cds_bootstrap.py").is_file()


def find_body_root(start=None):
    """Walk up from *start* (default: this file) looking for the sentinel."""
    current = Path(start).resolve() if start else Path(__file__).resolve().parent
    for candidate in [current] + list(current.parents):
        if body_is_valid(candidate):
            return candidate
    return None


def discover_script_dirs():
    """Every CODESYS ScriptDir that exists on this machine.

    Mirrors the install locations documented in docs/install.md. Returns them
    de-duplicated, in preference order.
    """
    candidates = []

    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "CODESYS" / "ScriptDir")

    program_data = os.environ.get("ProgramData")
    if program_data:
        candidates.append(Path(program_data) / "CODESYS" / "ScriptDir")

    patterns = [
        r"C:\Program Files\CODESYS *\CODESYS\ScriptDir",
        r"C:\Program Files (x86)\CODESYS *\CODESYS\ScriptDir",
        r"C:\Program Files\Delta Industrial Automation\DIAStudio\*\CODESYS\ScriptDir",
    ]
    for pattern in patterns:
        candidates.extend(Path(hit) for hit in sorted(glob.glob(pattern)))

    found = []
    seen = set()
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(candidate)
    return found


def script_dir_exposure(path):
    """How *path* is exposed to the CODESYS scanner.

    Returns (script_dir, kind) with kind either "contains" (the body is
    literally under a ScriptDir) or "links" (a ScriptDir holds a symlink or
    junction pointing at it -- the usual developer setup). The scanner follows
    reparse points, so both leave the internal modules in the menu.
    Returns (None, None) when the body is out of reach.
    """
    if not path:
        return None, None
    resolved = Path(path).resolve()
    branches = [resolved] + list(resolved.parents)

    for ancestor in branches:
        if ancestor.name.lower() == "scriptdir":
            return ancestor, "contains"

    script_dirs = discover_script_dirs()

    for script_dir in script_dirs:
        if script_dir.resolve() in branches:
            return script_dir, "contains"

    for script_dir in script_dirs:
        link = _link_into(script_dir, branches)
        if link is not None:
            return script_dir, "links"

    return None, None


def enclosing_script_dir(path):
    """The ScriptDir that exposes *path* to the scanner, or None."""
    return script_dir_exposure(path)[0]


def _link_into(script_dir, branches):
    """A reparse point at or under script_dir that resolves into branches."""
    try:
        candidates = [script_dir] + list(script_dir.iterdir())
    except OSError:
        return None
    for candidate in candidates:
        try:
            if not candidate.is_dir():
                continue
            target = candidate.resolve()
            if target != candidate and target in branches:
                return candidate
        except OSError:
            continue
    return None


def load_manifest(body_root):
    """Read ENTRYPOINTS out of the body's cds_bootstrap.py.

    Loaded by path rather than imported: an editable install only exposes the
    ``cds_text_sync`` package, and the body may not be on sys.path at all.
    """
    bootstrap = Path(body_root) / "cds_bootstrap.py"
    if not bootstrap.is_file():
        raise FileNotFoundError(str(bootstrap))
    spec = importlib.util.spec_from_file_location("_cds_manifest", str(bootstrap))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entrypoints = getattr(module, "ENTRYPOINTS", None)
    if not entrypoints:
        raise ValueError("cds_bootstrap.py defines no ENTRYPOINTS: " + str(bootstrap))
    return entrypoints


# -- rendering ---------------------------------------------------------------


def encode_path_literal(path):
    """Render *path* as an ASCII-only Python 2/3 unicode literal.

    Not a raw string: a raw literal cannot end in a backslash, and a plain
    byte literal holding UTF-8 Cyrillic is decoded by IronPython 2.7 as bytes,
    which then breaks sys.path and os.path.join. A user profile named in
    Cyrillic is entirely normal for this tool's audience, so escape everything
    outside printable ASCII.
    """
    out = []
    for char in str(path):
        code = ord(char)
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif 32 <= code < 127:
            out.append(char)
        elif code <= 0xFFFF:
            out.append("\\u%04x" % code)
        else:
            out.append("\\U%08x" % code)
    return 'u"' + "".join(out) + '"'


_STUB_TEMPLATE = '''# -*- coding: utf-8 -*-
{marker}
# Regenerate with: cts install-menu
"""{name}.py - CODESYS menu entry for cds-text-sync.

{summary}

The tool itself lives in CDS_HOME below; this file only points at it.
"""
import os
import sys

CDS_HOME = {home}

if CDS_HOME not in sys.path:
    sys.path.insert(0, CDS_HOME)

from cds_bootstrap import launch  # noqa: E402

_ENTRY = launch(
    "{name}",
    script_file=os.path.join(CDS_HOME, "{name}.py"),
    caller_globals=globals(),
)


def main(params=None):
    return _ENTRY(params=params)
{alias}

if __name__ == "__main__":
    main()
'''


def render_stub(spec, body_root):
    """Source text of one generated stub."""
    alias = spec.get("alias")
    alias_block = "\n\n{0} = main\n".format(alias) if alias else ""
    return _STUB_TEMPLATE.format(
        marker=MARKER,
        name=spec["name"],
        summary=spec.get("summary", "See docs/scripts.md."),
        home=encode_path_literal(body_root),
        alias=alias_block,
    )


# -- inspecting an existing menu folder --------------------------------------


def classify_menu_dir(menu_dir):
    """One of: missing, empty, stubs, flat, foreign."""
    menu_dir = Path(menu_dir)
    if not menu_dir.exists():
        return "missing"
    # "cds_text_sync" is the current body package; "cli" is what it was called
    # before 2.9, and a flat install predating the split still carries that name.
    if (
        (menu_dir / _SENTINEL_DIR).is_dir()
        or (menu_dir / "cds_text_sync").is_dir()
        or (menu_dir / "cli").is_dir()
    ):
        return "flat"
    entries = list(menu_dir.iterdir())
    if not entries:
        return "empty"
    py_files = [item for item in entries if item.is_file() and item.suffix == ".py"]
    if py_files and all(_has_marker(item) for item in py_files):
        return "stubs"
    return "foreign"


def _has_marker(path):
    try:
        with open(str(path), "r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(400)
    except OSError:
        return False
    return MARKER in head


def verify_menu(menu_dir, body_root):
    """Post-condition check. Empty list means the menu folder is exactly right."""
    menu_dir = Path(menu_dir)
    problems = []

    if not menu_dir.is_dir():
        return ["menu folder does not exist: " + str(menu_dir)]

    try:
        expected = set(spec["name"] + ".py" for spec in load_manifest(body_root))
    except (OSError, ValueError) as error:
        return ["cannot read the entrypoint manifest: " + str(error)]

    actual = set()
    for item in menu_dir.iterdir():
        if item.is_dir():
            if item.name in _DISPOSABLE_DIRS:
                continue
            problems.append("unexpected subdirectory in the menu folder: " + item.name)
            continue
        actual.add(item.name)

    for name in sorted(expected - actual):
        problems.append("missing stub: " + name)
    for name in sorted(actual - expected):
        problems.append("unexpected file in the menu folder: " + name)

    home_literal = encode_path_literal(body_root)
    for name in sorted(expected & actual):
        path = menu_dir / name
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            problems.append("cannot read " + name + ": " + str(error))
            continue
        if MARKER not in text:
            problems.append("not a generated stub (hand-edited?): " + name)
        elif home_literal not in text:
            problems.append("stub points at a different body: " + name)

    return problems


# -- the actual work ---------------------------------------------------------


class MenuError(Exception):
    """A refusal that should reach the user as a message, not a traceback."""


def resolve_script_dir(explicit=""):
    if explicit:
        return Path(explicit)
    found = discover_script_dirs()
    if not found:
        raise MenuError(
            "No CODESYS ScriptDir found on this machine. "
            "Pass --script-dir <path> explicitly."
        )
    return found[0]


def write_menu(body_root, script_dir, force=False, prune=False, dry_run=False,
               allow_body_in_scriptdir=False):
    """Render the stubs into <script_dir>/cds-text-sync. Idempotent."""
    body_root = Path(body_root).resolve()
    script_dir = Path(script_dir)
    warnings = []

    if not body_is_valid(body_root):
        raise MenuError("not a cds-text-sync tree: " + str(body_root))

    offender, exposure = script_dir_exposure(body_root)
    if offender is not None:
        if exposure == "links":
            remedy = (
                "That ScriptDir holds a link pointing at the tool, and the scanner\n"
                "follows it. Remove the link itself -- not its target:\n"
                "    [System.IO.Directory]::Delete(\""
                + str(offender / MENU_FOLDER) + "\", $false)\n"
                "then re-run this command."
            )
        else:
            remedy = (
                "Move the tool out first, for example:\n"
                "    Move-Item \"" + str(body_root) + "\" \""
                + str(default_body_root()) + "\"\n"
                "then re-run this command from the new location."
            )
        message = (
            "the tool is exposed to the CODESYS script scanner:\n"
            "    " + str(body_root) + "\n"
            "    (ScriptDir: " + str(offender) + ")\n"
            "CODESYS scans ScriptDir recursively, so every internal module stays\n"
            "in the Tools > Scripting menu and generating stubs changes nothing.\n"
            + remedy
        )
        if not allow_body_in_scriptdir:
            raise MenuError(message)
        warnings.append(message)

    menu_dir = script_dir / MENU_FOLDER
    layout = classify_menu_dir(menu_dir)
    if layout == "flat" and not force:
        raise MenuError(
            "a full installation lives in " + str(menu_dir) + ".\n"
            "Moving user data is the installer's job, not this command's.\n"
            "Run the installer to migrate, or pass --force to overwrite in place."
        )

    manifest = load_manifest(body_root)
    written, unchanged, removed = [], [], []

    if not dry_run:
        menu_dir.mkdir(parents=True, exist_ok=True)

    expected_names = set()
    for spec in manifest:
        name = spec["name"] + ".py"
        expected_names.add(name)
        target = menu_dir / name
        source = render_stub(spec, body_root)

        current = None
        if target.is_file():
            try:
                current = target.read_text(encoding="utf-8")
            except OSError:
                current = None
        if current == source:
            unchanged.append(name)
            continue

        written.append(name)
        if not dry_run:
            with open(str(target), "w", encoding="utf-8", newline="\n") as handle:
                handle.write(source)

    if menu_dir.is_dir():
        for item in sorted(menu_dir.iterdir()):
            if item.is_dir():
                if item.name in _DISPOSABLE_DIRS:
                    if not dry_run:
                        _remove_tree(item)
                    removed.append(item.name)
                elif prune and not dry_run:
                    _remove_tree(item)
                    removed.append(item.name)
                else:
                    warnings.append("unexpected subdirectory left in place: " + item.name)
                continue
            if item.name in expected_names:
                continue
            # A stub we generated but no longer ship is ours to clean up.
            if _has_marker(item) or prune:
                removed.append(item.name)
                if not dry_run:
                    item.unlink()
            else:
                warnings.append(
                    "unexpected file left in place (use --prune to remove): " + item.name
                )

    problems = [] if dry_run else verify_menu(menu_dir, body_root)

    return {
        "body_root": str(body_root),
        "menu_dir": str(menu_dir),
        "layout_before": layout,
        "written": written,
        "unchanged": unchanged,
        "removed": removed,
        "warnings": warnings,
        "problems": problems,
        "dry_run": bool(dry_run),
    }


def _remove_tree(path):
    for child in sorted(path.iterdir(), reverse=True):
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()
    path.rmdir()


def describe(body_root=None, script_dir=None):
    """Backing data for ``cts where``."""
    body = Path(body_root) if body_root else find_body_root()
    info = {
        "body_root": str(body) if body else None,
        "body_valid": bool(body and body_is_valid(body)),
        "install_menu_module": str(Path(__file__).resolve()),
        "script_dirs": [],
    }

    if body:
        offender, exposure = script_dir_exposure(body)
        info["body_inside_script_dir"] = str(offender) if offender else None
        info["exposure"] = exposure
        try:
            info["entrypoints"] = [spec["name"] for spec in load_manifest(body)]
        except (OSError, ValueError):
            info["entrypoints"] = []
    else:
        info["body_inside_script_dir"] = None
        info["exposure"] = None
        info["entrypoints"] = []

    targets = [Path(script_dir)] if script_dir else discover_script_dirs()
    for target in targets:
        menu_dir = target / MENU_FOLDER
        entry = {
            "script_dir": str(target),
            "menu_dir": str(menu_dir),
            "layout": classify_menu_dir(menu_dir),
            "problems": [],
        }
        if entry["layout"] in ("stubs", "foreign") and info["body_valid"]:
            entry["problems"] = verify_menu(menu_dir, body)
        info["script_dirs"].append(entry)

    info["layout"] = _overall_layout(info)
    return info


def _overall_layout(info):
    layouts = set(entry["layout"] for entry in info["script_dirs"])
    if "flat" in layouts:
        return "flat"
    if "stubs" in layouts:
        return "split"
    return "unknown"


# -- command line ------------------------------------------------------------


def add_menu_arguments(parser):
    """Shared by ``cts install-menu`` and ``python -m cds_text_sync.install_menu``."""
    parser.add_argument(
        "--body", default="",
        help="Folder holding the tool itself (default: the tree this module lives in)",
    )
    parser.add_argument(
        "--script-dir", dest="script_dir", default="",
        help="CODESYS ScriptDir to write the menu into (default: auto-detect)",
    )
    parser.add_argument(
        "--all-script-dirs", action="store_true",
        help="Write the menu into every CODESYS ScriptDir found on this machine",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would change without writing anything",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite a full installation sitting in the menu folder",
    )
    parser.add_argument(
        "--prune", action="store_true",
        help="Delete unexpected files found in the menu folder",
    )
    parser.add_argument(
        "--allow-body-in-scriptdir", action="store_true",
        help="Proceed even though the tool itself sits inside a ScriptDir",
    )
    return parser


def run_from_args(args):
    """Execute install-menu for parsed *args*. Returns a list of result dicts."""
    body = Path(args.body).resolve() if getattr(args, "body", "") else find_body_root()
    if body is None:
        raise MenuError(
            "cannot find the cds-text-sync tree. Pass --body <path> explicitly."
        )

    if getattr(args, "all_script_dirs", False):
        targets = discover_script_dirs()
        if not targets:
            raise MenuError("No CODESYS ScriptDir found on this machine.")
    else:
        targets = [resolve_script_dir(getattr(args, "script_dir", ""))]

    results = []
    for target in targets:
        results.append(write_menu(
            body,
            target,
            force=getattr(args, "force", False),
            prune=getattr(args, "prune", False),
            dry_run=getattr(args, "dry_run", False),
            allow_body_in_scriptdir=getattr(args, "allow_body_in_scriptdir", False),
        ))
    return results


def format_result(result):
    lines = []
    verb = "would write" if result["dry_run"] else "wrote"
    lines.append("Menu : " + result["menu_dir"])
    lines.append("Body : " + result["body_root"])
    lines.append("       {0} {1}, unchanged {2}, removed {3}".format(
        verb, len(result["written"]), len(result["unchanged"]), len(result["removed"])))
    for warning in result["warnings"]:
        lines.append("[WARN] " + warning)
    for problem in result["problems"]:
        lines.append("[PROBLEM] " + problem)
    return "\n".join(lines)


def main(argv=None):
    try:
        from cds_text_sync._stdio import configure_stdio_utf8
    except ImportError:  # executed as a bare script: cds_text_sync/ is sys.path[0]
        from _stdio import configure_stdio_utf8
    configure_stdio_utf8()

    parser = argparse.ArgumentParser(
        prog="install-menu",
        description=(
            "Write the CODESYS Tools>Scripting stubs into ScriptDir. "
            "Only the public Project_*.py entry points are generated; "
            "the tool itself stays outside ScriptDir so it is not scanned."
        ),
    )
    add_menu_arguments(parser)
    args = parser.parse_args(argv)

    try:
        results = run_from_args(args)
    except MenuError as error:
        print("[ERROR] " + str(error), file=sys.stderr)
        return 2

    failed = False
    for result in results:
        print(format_result(result))
        if result["problems"]:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
