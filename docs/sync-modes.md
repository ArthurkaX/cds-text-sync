# Sync Modes

The sync mode is chosen **once, on an empty sync folder** (in
`Project_options.py`, before the first export) and is fixed for the lifetime of
that folder. To switch modes, initialize a new empty sync folder. The mode is
recorded in `.dump/manifest.json`; the engine refuses a mismatched
`cds-text-sync.json`.

In the **Project Options** dialog the "Text-first mode" checkbox is the paradigm
selector, and the single derived-files list beneath it follows the selected
mode — the two modes' lists are mutually exclusive, so only the relevant one is
shown:

| Mode | List shown | You choose |
|------|-----------|------------|
| XML-first | **Derived views** | which optional `.st`/`.csv` projections to generate |
| Text-first | **Keep XML in view** | which kinds keep their native `.xml` in the view instead of the `.dump/xml/` mirror (`.st` is always on) |

Toggle the checkbox and the list swaps in place. Once the folder is initialized
the checkbox is locked (the mode cannot change), but the "Keep XML in view"
selection can still be adjusted at any time.

## XML-first (default)

Native XML in the view root is the canonical round-trip format; optional
`.st`/`.csv` projections make code readable. This is the behavior the rest of
the documentation describes unless it says otherwise.

## Text-first (opt-in)

For teams that treat the `.st` files on disk as the source of truth (e.g. heavy
external-editor or LLM workflows):

- **`.st` projections are always on** for every ST-capable kind — no
  per-projection opt-in needed.
- **Structural XML moves out of the view**: the tool-owned copies live in the
  git-ignored `.dump/xml/` mirror, so the tracked view contains text, not XML. A
  per-kind "Keep XML in view for:" list (`xml_in_view_kinds`, default
  `["visu"]`) keeps hand-edited XML kinds such as visualizations in the view and
  in Git.
- **`.st` files are first-class import input**: edits are picked up even when the
  manifest never registered them; a hand-made `.st` (with or without a sidecar
  `.xml`) becomes a new object; a teammate's fresh clone (no `.dump/`) still
  imports — the `.st` text is overlaid on a fresh IDE baseline.
- **Unmanaged `.st` files are never deleted** by export.
- On conflicting edits (IDE and disk), **the `.st` text wins**.

Kinds without an ST form (devices, task configuration, …) become effectively
export-only in text-first mode unless kept in the view via `xml_in_view_kinds`.

## Overwrite protection (both modes)

Export never silently overwrites files you edited on disk but have not imported
yet, and never deletes unmanaged files without asking:

- **Interactive** (`Project_export.py`): a review dialog lists the
  locally-modified files and the unmanaged derived files, with two independent,
  default-off checkboxes — "Overwrite my local changes" and "Remove the unmanaged
  derived files" — plus Continue / Cancel.
- **Headless / daemon / CLI**: dirty files are **skipped by default** — they keep
  their content, their previous manifest hashes are carried forward (so the next
  import still sees the edits), and they are reported as "pending import".
  Unmanaged derived files are **kept and reported** (never deleted). Pass
  `overwrite_dirty=true` / `--overwrite-dirty` to regenerate modified files, and
  `remove_orphans=true` / `--remove-orphans` to delete unmanaged ones — the two
  are independent.
- The engine subcommand `check-dirty` writes `.dump/dirty_report.json` with the
  current dirty/orphan lists without touching anything.

## Related

- [Project layout](project-layout.md) — what lands where on disk
- [profiles/profiles.md](../profiles/profiles.md) — profile-driven object
  behavior and projection availability
