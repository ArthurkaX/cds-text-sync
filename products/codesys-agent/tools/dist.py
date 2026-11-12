"""Refresh dist/: build the agent and cts.exe in Release, check them, and copy them there.

dist/ is in Git LFS. A download from a branch installs these files beside the
menu, so a user needs no .NET SDK. The build names the commit it was built
from (`cts --version`, the agent's hello), so the source is committed first and
the refreshed files go in a commit of their own after it:

    git commit ...                                   # the change
    python products/codesys-agent/tools/dist.py
    git commit -m "dist: the build of <commit>" products/codesys-agent/dist

Nothing is copied unless every check passes: the C# tests, DeadSymbols, the
repository's Python tests and Ruff lint (through uv, with requirements-dev.txt)
and no Cyrillic text in the repository. `--check` builds and runs those checks
and copies nothing: what CI runs on every push.
"""

import argparse
import shutil
import subprocess
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1]
REPO = AGENT.parents[1]
FILES = {
    "Cts.Agent": ("Cts.Agent.Core.dll", "Cts.Agent.dll"),
    "Cts.Cli": ("cts.exe", "cts.exe.config"),
}


def run(argv, cwd):
    """One build or check step; a failing one ends the refresh."""
    if subprocess.run(argv, cwd=cwd).returncode != 0:
        raise SystemExit("dist not refreshed: `{0}` failed".format(" ".join(argv)))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="build and check; copy nothing")
    check_only = parser.parse_args().check
    changed = subprocess.run(["git", "-C", str(AGENT), "status", "--porcelain", "--", "src", "Directory.Build.props"],
                             check=True, capture_output=True, text=True).stdout
    if changed and not check_only:
        raise SystemExit("commit the source first: the build names the commit it was built from\n" + changed)
    # dotnet runs in the agent's folder, where global.json names the SDK.
    for project in FILES:
        run(["dotnet", "build", str(AGENT / "src" / project), "-c", "Release"], AGENT)
    run(["dotnet", "test", str(AGENT / "tests" / "Cts.Agent.Core.Tests"), "--verbosity", "quiet"], AGENT)
    run(["dotnet", "run", "-c", "Release", "--project", str(AGENT / "tools" / "DeadSymbols")], AGENT)
    run(["uv", "run", "--no-project", "--with-requirements", "requirements-dev.txt",
         "python", "-m", "pytest", "-q", "tests/unit", "-p", "no:cacheprovider"], REPO)
    run(["uv", "run", "--no-project", "--with-requirements", "requirements-dev.txt",
         "ruff", "check", "."], REPO)
    cyrillic = subprocess.run(["git", "grep", "-nIP", "[\\x{0400}-\\x{04FF}]"], cwd=REPO, capture_output=True, text=True).stdout
    if cyrillic:
        raise SystemExit("dist not refreshed: Cyrillic text in the repository\n" + cyrillic)
    if check_only:
        print("all checks passed")
        return
    dist = AGENT / "dist"
    dist.mkdir(exist_ok=True)
    for project, names in FILES.items():
        out = AGENT / "src" / project / "bin" / "Release" / "net48"
        for name in names:
            shutil.copy2(out / name, dist / name)
            print(dist / name)


if __name__ == "__main__":
    main()
