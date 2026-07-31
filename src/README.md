# Source layout

`src/` holds the tree that runs inside CODESYS: `ide_bridge/`.

## Two interpreters, never mixed

Everything under `src/ide_bridge/` is loaded inside the CODESYS IDE, which embeds
IronPython 2.7. It must stay Python-2-compatible: no f-strings, no walrus
operator, no `pathlib`, no type annotations, no `subprocess.run`
(`subprocess.Popen` is fine, and most modules start with `from __future__`).

The rest of the repo — the `cds_text_sync/` package — is ordinary CPython 3.8+ and has none
of those restrictions. The two trees must not import each other directly; `cds_text_sync/`
reaches the bridge only through the root `cds_bootstrap.py`.

## Not a package

There is no `__init__.py` in `src/` or `src/ide_bridge/`. Modules are imported by
name, not as a package — `cds_bootstrap.import_runtime_module` puts
`src/ide_bridge` on `sys.path` and imports by name.

`src/ide_bridge` is also a load-bearing sentinel: `codesys_runtime._get_root_dir`
walks up the tree looking for it, and `cds_text_sync/install_menu.py` checks it to
validate an install. Do not rename or move it.

## Indentation

Every module here uses 4-space indents. The root `cds_bootstrap.py` is the one
exception in the whole tool — it uses 1-space indents. Match the file you are
editing rather than reformatting it, and never reformat a file as a side effect
of an unrelated change.
