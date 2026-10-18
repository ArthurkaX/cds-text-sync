"""Refresh dist/: build the agent and cts.exe in Release and copy them there.

dist/ is in Git LFS. A download from a branch installs these files beside the
menu, so a user needs no .NET SDK. The build names the commit it was built
from (`cts --version`, the agent's hello), so the source is committed first and
the refreshed files go in a commit of their own after it:

    git commit ...                                   # the change
    python products/codesys-agent/tools/dist.py
    git commit -m "dist: the build of <commit>" products/codesys-agent/dist
"""

import shutil
import subprocess
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1]
FILES = {
    "Cts.Agent": ("Cts.Agent.Core.dll", "Cts.Agent.dll"),
    "Cts.Cli": ("cts.exe", "cts.exe.config"),
}


def main():
    changed = subprocess.run(["git", "-C", str(AGENT), "status", "--porcelain", "--", "src", "Directory.Build.props"],
                             check=True, capture_output=True, text=True).stdout
    if changed:
        raise SystemExit("commit the source first: the build names the commit it was built from\n" + changed)
    dist = AGENT / "dist"
    dist.mkdir(exist_ok=True)
    for project, names in FILES.items():
        subprocess.run(["dotnet", "build", str(AGENT / "src" / project), "-c", "Release"], check=True)
        out = AGENT / "src" / project / "bin" / "Release" / "net48"
        for name in names:
            shutil.copy2(out / name, dist / name)
            print(dist / name)


if __name__ == "__main__":
    main()
