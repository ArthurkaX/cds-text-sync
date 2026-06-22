# codesys-visu skill

This skill teaches AI agents to author CODESYS visualizations using the
`cts visu` command group (part of the `cds-text-sync` repository).

## Versioning

This skill is versioned **inside** the `cds-text-sync` repository so it stays
in sync with the tool code. The old monolithic skill at
`C:\Users\arthu\.agents\skills\codesys-visu` is deprecated; migrate to this one.

## Usage (for an AI agent harness)

Symlink or copy this directory into the agent's skills directory:

```
# Example (Windows PowerShell, admin):
New-Item -ItemType SymbolicLink -Path "C:\Users\arthu\.agents\skills\codesys-visu" `
  -Target "C:\Workspace\Active\cds-text-sync\skills\codesys-visu"
```

On POSIX:
```
ln -s /path/to/cds-text-sync/skills/codesys-visu ~/.agents/skills/codesys-visu
```

The entry file is `SKILL.md`; the agent harness should load it when the
`codesys-visu` skill is activated.
