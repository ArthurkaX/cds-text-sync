# Source layout

This directory holds what CODESYS runs from this repository as a script:
`headless/plc_crc.py`, the CRC check `cts plc-crc-headless` starts CODESYS with
(`--runscript`). The menu entry is not here: `cts install` (cts.exe) writes it
and the in-IDE agent it loads.

## Two interpreters, never mixed

`headless/plc_crc.py` runs inside the CODESYS IDE, which embeds IronPython 2.7.
It must stay Python-2-compatible: no f-strings, no walrus operator, no
`pathlib`, no type annotations, no `subprocess.run`. `tools/compat_check.py`
checks it.
