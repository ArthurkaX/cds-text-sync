---
name: cds-text-sync
description: Operate the CODESYS text sync CLI (`cts`) safely across an exported project folder, the CODESYS IDE daemon, and a PLC. Use for `cts` command selection, folder/IDE synchronization, builds and downloads, PLC lifecycle or variable access, offline engine operations, and troubleshooting cds-text-sync workflows.
disable-model-invocation: true
---

# Operate CODESYS Text Sync

The operating rules ship inside the package, so they always match the installed
CLI version. Read them with:

```sh
cts guide            # list the topics and the guide directory
cts guide workflow   # these rules: state model, mutation scope, reporting
cts guide commands   # routing table: which command for which job
cts guide visu-svg   # authoring SVG sketches that compile into HMI screens
```

Start with `cts guide workflow` rather than working from memory: the guide is
replaced whenever the CLI is upgraded, and this file is not.

Treat the exported project folder as the source of truth unless the user
explicitly requests recovery or export from the IDE.
