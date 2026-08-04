"""
ci_analyze_checks.py - CI guard for the ``cts analyze`` package.

Run inside CI (or locally) after the unit tests:

    python tools/ci_analyze_checks.py selftest # rules against their docs
    python tools/ci_analyze_checks.py wheel    # wheel assets + clean-venv install
    python tools/ci_analyze_checks.py all      # both (default)

Kept as a file (not inline shell) so the workflow stays readable and the
same checks can run on a dev machine.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tempfile
import venv
import zipfile


def check_selftest():
    """Every rule must pass its own good/bad documentation examples."""
    from cds_text_sync.main import main

    old_argv = sys.argv
    sys.argv = ["cts", "analyze", "selftest"]
    try:
        code = main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    finally:
        sys.argv = old_argv
    if code:
        raise SystemExit(f"selftest failed with exit code {code}")


def _build_wheel(root, wheel_dir):
    """Build the wheel into *wheel_dir*; return the wheel path."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "-w",
            wheel_dir,
            "--no-deps",
            "--no-cache-dir",
            "-q",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"pip wheel failed: {proc.stderr[-500:]}")
    wheels = glob.glob(os.path.join(wheel_dir, "*.whl"))
    if not wheels:
        raise SystemExit("no wheel produced")
    return wheels[0]


def check_wheel_assets():
    """The wheel must ship rule docs, the UI page, and no leaked bytecode."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    with tempfile.TemporaryDirectory() as wheel_dir:
        wheel = _build_wheel(root, wheel_dir)
        names = zipfile.ZipFile(wheel).namelist()
        rules = [n for n in names if "/analyze/rules/" in n]
        rule_py = [n for n in rules if n.endswith(".py")]
        docs = [n for n in rules if n.endswith(".md")]
        if len(rule_py) != 22:
            raise SystemExit(f"expected 22 rule .py files in wheel, got {len(rule_py)}")
        if len(docs) != 22:
            raise SystemExit(f"expected 22 .md in wheel, got {len(docs)}")
        ui_pages = [n for n in names if n.endswith("cds_text_sync/ui_assets/index.html")]
        if len(ui_pages) != 1:
            raise SystemExit("desktop UI page missing from wheel")
        leaked = [n for n in rules if n.endswith(".pyc")]
        if leaked:
            raise SystemExit(f".pyc leaked into wheel rules: {leaked}")
        print(
            f"wheel OK: {len(rule_py)} human rules, {len(docs)} docs, "
            "UI page, no pyc leaked"
        )


def _venv_bin(venv_dir):
    """Scripts (Windows) or bin (POSIX) directory of a venv."""
    return os.path.join(venv_dir, "Scripts" if os.name == "nt" else "bin")


def _venv_python(venv_dir):
    return os.path.join(
        _venv_bin(venv_dir), "python.exe" if os.name == "nt" else "python"
    )


def _venv_cts(venv_dir):
    return os.path.join(_venv_bin(venv_dir), "cts.exe" if os.name == "nt" else "cts")


def check_wheel_install():
    """A clean venv must install the wheel and run the installed CLI.

    Archive assertions alone cannot prove that package data, registry
    loading, and the installed entry point work from a clean environment.
    The commands run with ``cwd`` outside the source checkout so local
    files cannot mask package defects.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    with tempfile.TemporaryDirectory() as tmp:
        wheel = _build_wheel(root, os.path.join(tmp, "wheel"))
        venv_dir = os.path.join(tmp, "venv")
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        py = _venv_python(venv_dir)
        cts = _venv_cts(venv_dir)

        proc = subprocess.run(
            [py, "-m", "pip", "install", wheel, "--no-deps", "-q"],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise SystemExit(f"venv install failed: {proc.stderr[-500:]}")
        if not os.path.isfile(cts):
            raise SystemExit(f"entry point not installed in venv: {cts}")

        neutral = os.path.join(tmp, "run")
        os.makedirs(neutral, exist_ok=True)

        proc = subprocess.run(
            [cts, "analyze", "rules", "--format", "json"],
            cwd=neutral,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise SystemExit(
                f"installed 'cts analyze rules' failed ({proc.returncode}):\n"
                f"{proc.stdout[-500:]}\n{proc.stderr[-500:]}"
            )
        try:
            rows = json.loads(proc.stdout)
        except ValueError as exc:
            raise SystemExit(
                f"installed 'cts analyze rules' produced non-JSON output: "
                f"{exc}\n{proc.stdout[:500]}"
            ) from exc
        ids = {row.get("id") for row in rows}
        if ids != {"CTS0001", "CTS0002", "CTS0003", "CTS0004", "CTS0006", "CTS0007", "CTS0008", "CTS0009", "CTS0010", "CTS0011", "CTS0012", "CTS0013", "CTS0014", "CTS0015", "CTS0016", "CTS0017", "CTS0018", "CTS0019", "CTS0020", "CTS0021", "CTS0022", "CTS0023"}:
            raise SystemExit(
                f"installed registry reports {sorted(ids)}; "
                "expected the eighteen human-analysis rules"
            )

        proc = subprocess.run(
            [cts, "analyze", "selftest"],
            cwd=neutral,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise SystemExit(
                f"installed 'cts analyze selftest' failed ({proc.returncode}):\n"
                f"{proc.stdout[-500:]}\n{proc.stderr[-500:]}"
            )
        print("wheel install OK: venv entry point lists 22 human rules, selftest passes")


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "all"
    if command in ("selftest", "all"):
        check_selftest()
    if command in ("wheel", "all"):
        check_wheel_assets()
        check_wheel_install()
    print("ci_analyze_checks: OK")


if __name__ == "__main__":
    main()
