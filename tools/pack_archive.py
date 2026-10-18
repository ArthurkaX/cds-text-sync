"""Pack a commit as a setup kit: what the irm installer downloads, as one file.

The kit is a zip holding the source archive of the commit (the agent binaries
taken from Git LFS, not pointers), the commit's ``irm/setup.ps1`` and an
``install.cmd`` that runs it on that archive (``CTS_ARCHIVE``). Unzipped on
Windows, a double click on install.cmd installs the build as irm would,
without GitHub.

Usage::

    python3 tools/pack_archive.py              # HEAD into ~/Downloads
    python3 tools/pack_archive.py nightly --out DIR
"""

import argparse
import io
import os
import subprocess
import sys
import zipfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AGENT_DIST = "products/codesys-agent/dist/"

_INSTALL_CMD = """@echo off
rem Installs cds-text-sync from the archive beside this file.
set "CTS_ARCHIVE=%~dp0{archive}"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
pause
"""


def _git(*args):
    return subprocess.run(("git", "-C", _ROOT) + args, check=True,
                          stdout=subprocess.PIPE).stdout


def _kit_name(ref):
    sha = _git("rev-parse", "--short=8", ref + "^{commit}").decode().strip()
    name = ref
    if ref == "HEAD":
        name = _git("rev-parse", "--abbrev-ref", "HEAD").decode().strip()
    return "cds-text-sync-%s-%s" % (name.replace("/", "-"), sha)


def _archive(ref, kit):
    data = _git("archive", "--format=zip", "--prefix=%s/" % kit, ref)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.namelist():
            if (entry.startswith(kit + "/" + _AGENT_DIST)
                    and archive.read(entry).startswith(b"version https://git-lfs")):
                sys.exit("%s is a Git LFS pointer: run `git lfs install` "
                         "and `git lfs pull`, then pack again" % entry)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ref", nargs="?", default="HEAD")
    parser.add_argument("--out", default=os.path.expanduser("~/Downloads"))
    options = parser.parse_args()

    kit = _kit_name(options.ref)
    archive_name = kit + ".zip"
    files = {
        archive_name: _archive(options.ref, kit),
        "setup.ps1": _git("show", options.ref + ":irm/setup.ps1"),
        "install.cmd": _INSTALL_CMD.format(archive=archive_name)
                       .replace("\n", "\r\n").encode("ascii"),
    }
    os.makedirs(options.out, exist_ok=True)
    path = os.path.join(options.out, kit + "-setup.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as setup:
        for name, data in files.items():
            setup.writestr("%s-setup/%s" % (kit, name), data)
    print(path)


if __name__ == "__main__":
    main()
