# -*- coding: utf-8 -*-
"""
cds_cli.py — alias for cds_text_sync.py

This file exists for backward compatibility.
Use cds_text_sync.py or cds-text-sync.bat instead.
"""

import sys
from pathlib import Path

# Redirect to cds_text_sync.py
_script_dir = Path(__file__).resolve().parent
_main_script = _script_dir / "cds_text_sync.py"

if _main_script.exists():
    # Replace this process's entry
    sys.argv[0] = str(_main_script)
    with open(_main_script, encoding="utf-8") as f:
        code = compile(f.read(), str(_main_script), "exec")
    exec(code, {"__name__": "__main__", "__file__": str(_main_script)})
else:
    print(f"[ERROR] cds_text_sync.py not found at {_main_script}")
    sys.exit(1)
