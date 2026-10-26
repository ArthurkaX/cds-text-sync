# Documentation

Start at the [project README](../readMe.md) for what the tool is and a quick
start. These pages are the detail.

## Setting up

- **[Installation](install.md)** — requirements, both install methods, installing
  the `cts` CLI, and upgrading from a previous version.
- **[Alternative installations](alternative-installations.md)** — forks and
  non-standard CODESYS environments (DIAStudio, legacy script paths).

## Using it

- **[Script overview](scripts.md)** — how to use the `cds-text-sync` menu entry,
  in the order you use them, plus the default `.st`/`.csv` text exports.
- **CLI reference** — run `cts --help`, `cts <command> --help`, and `cts guide`
  for the reference shipped with the installed version.
- **[HMI screens from SVG](visu.md)** — `cts visu` end to end: prerequisites, the
  chain from sketch to a screen in CODESYS, PLC variable binding, themes and
  schemes, and handing the workflow to an LLM agent.

- **[Static analysis](analyze.md)** — `cts analyze` over the exported `.st`
  files: rules, settings, baseline and triage, the findings window.

## Working with others

- **[Upgrading to 4.0](upgrade-4.md)** — install, update and go back to 3.4.1; what changes on upgrade, known limits, reporting problems.
- **[Working as a team](team.md)** — the owner and colleagues on one repository:
  setting it up, committing, taking the team's work, and same-line edits.
- **[Releases & rollback](releases.md)** — stable tags, version policy, and how to
  revert safely.

## Reference

- **[Operating guides](../products/codesys-agent/src/Cts.Agent.Core/Guides/)** — embedded in cts.exe and served offline with `cts guide` (workflow, commands, SVG authoring contract). See also
  [the skill wrapper](../skills/cds-visu-svg/SKILL.md).
- **[Changelog](../CHANGELOG.md)**
