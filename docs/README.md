# Documentation

Start at the [project README](../readMe.md) for what the tool is and a quick
start. These pages are the detail.

## Setting up

- **[Installation](install.md)** — requirements, both install methods, installing
  the `cts` CLI, and upgrading from a previous version.
- **[Alternative installations](alternative-installations.md)** — forks and
  non-standard CODESYS environments (DIAStudio, legacy script paths).
- **[Sync modes](sync-modes.md)** — XML-first vs text-first, chosen once per sync
  folder, and how overwrite protection behaves in each.

## Using it

- **[Script overview](scripts.md)** — what each `Project_*.py` entry point does,
  in the order you use them, plus the optional `.st`/`.csv` projections.
- **[Project layout](project-layout.md)** — the on-disk structure, what to track
  and what to ignore, the day-to-day edit cycle, and Git LFS for `.project`.
- **[CLI reference](../cli/CLI.md)** — every `cts` command and flag, the
  reverse-pipe daemon, timeouts, error modes.
- **[HMI screens from SVG](visu.md)** — `cts visu` end to end: prerequisites, the
  chain from sketch to a screen in CODESYS, PLC variable binding, themes and
  schemes, and handing the workflow to an LLM agent.

## Working with others

- **[Team workflow](workflow.md)** — branches and pull requests for HMI/hardware
  engineers and software developers.
- **[Releases & rollback](releases.md)** — stable tags, version policy, and how to
  revert safely.

## Reference

- **[Profiles](../profiles/profiles.md)** — vendor/fork object kinds, projection
  availability, safety rules.
- **[SVG authoring contract](../skills/cds-visu-svg/SKILL.md)** — layout rules,
  the type scale, and the conventions an authoring model is expected to follow.
- **[Changelog](../CHANGELOG.md)** · **[Contributing](../CONTRIBUTING.md)** ·
  **[Security](../SECURITY.md)**
