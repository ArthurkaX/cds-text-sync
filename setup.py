# -*- coding: utf-8 -*-
"""
setup.py — pip-installable entry point for cds-text-sync.

Usage:
    pip install -e .           # development mode (creates cds-text-sync.exe)
    pip install .              # regular install

After install, `cds-text-sync` works in any shell (CMD, PowerShell, Git Bash).
"""

from setuptools import setup, find_packages

setup(
    name="cds-text-sync",
    version="2.5.1",
    description="CODESYS CLI + reverse-pipe daemon",
    author="cds-text-sync contributors",
    url="https://github.com/ArthurkaX/cds-text-sync",
    packages=find_packages(include=["cli", "cli.*"]),
    package_data={
        "cli": ["MANUAL.md", "cicd-format.md"],
    },
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "cds-text-sync=cli.cds_text_sync:main",
        ],
    },
    include_package_data=True,
)
