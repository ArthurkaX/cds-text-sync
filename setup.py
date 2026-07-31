# -*- coding: utf-8 -*-
"""
setup.py — pip-installable entry point for cds-text-sync.

Usage:
    pip install -e .           # development mode (creates cds-text-sync.exe)
    pip install .              # regular install

After install, `cts` and `cds-text-sync` work in any shell (CMD, PowerShell, Git Bash).
"""

import io
import os
import re

from setuptools import find_packages, setup


def _read_version():
    here = os.path.dirname(os.path.abspath(__file__))
    init_path = os.path.join(here, "cds_text_sync", "__init__.py")
    with io.open(init_path, encoding="utf-8") as f:
        match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', f.read(), re.M)
    if not match:
        raise RuntimeError("Unable to find __version__ in cds_text_sync/__init__.py")
    return match.group(1)


setup(
    name="cds-text-sync",
    version=_read_version(),
    description="CODESYS CLI + reverse-pipe daemon",
    author="cds-text-sync contributors",
    url="https://github.com/ArthurkaX/cds-text-sync",
    packages=find_packages(include=["cds_text_sync", "cds_text_sync.*"]),
    package_data={
        "cds_text_sync": ["CLI.md", "TEST_FORMAT.md"],
        "cds_text_sync.engine": ["sys_funcs.json"],
        "cds_text_sync.visu": [
            "catalog/*.json",
            "templates/*.tmpl",
            "themes/*.json",
            "styles_snapshot.json",
            "stylesheet.css",
            "DESIGN.md",
        ],
    },
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "cds-text-sync=cds_text_sync.cds_text_sync:main",
            "cts=cds_text_sync.cds_text_sync:main",
        ],
    },
    include_package_data=True,
)
