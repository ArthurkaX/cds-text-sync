# Status

`cts status` starts with `ok status ide=ide-7236 plc=offline edits=allowed unsaved=false`, then the sync folder, where its git is (`git branch=master commit=d63b78a5 uncommitted=0`; the open project's own file does not count, and `git none` when the folder is not set up), the project file and the last command; `--json` prints the whole payload. The in-IDE agent answers it from the IDE itself: the open project, its sync folder, whether it has unsaved changes and whether an application is logged in (`plc.online`, `plc.application_state`). It answers while a dialog is on screen, and it fails quickly if the agent does not answer.

Every command that talks to CODESYS runs in the agent. Start it inside CODESYS: **Tools > Scripting > Scripts > C > cds-text-sync**. Then retry `cts status`.

From the CLI instead of the menu:

- `cts project open --path <project> --launch` — starts CODESYS on that project with the `cds-text-sync` stub as its startup script, and waits until the agent answers. Use it on a machine where the IDE is not running yet. `--profile "<name>"` selects the CODESYS profile to start with.

When a command gets no answer, `cts` says which case it is instead of guessing:

- **the IDE is busy** — the agent answers, but the IDE's UI thread did not run the command in time; retry once the IDE is idle;
- **the IDE is blocked by a dialog** — a modal dialog is on screen and nothing can run until it is answered. The line names the dialog, with its options and buttons and a short id; the command is not sent, so there is no 30-second wait to sit through. `cts dialog answer` answers it from here (see below);
- **no agent answers** — no `cts-agent` pipe was found.

A dialog can also appear *while* a command runs. The CLI watches for that too
and ends the wait after a couple of seconds instead of the whole timeout, with
exit code 3 and error code `dialog_opened` (see `cts guide dialog`). The
command is not cancelled — it is still running in the IDE — and once you have
answered the dialog, `cts status` reports how the last build of this project
ended (no other command keeps a record):

- **`last_command`** — the last build since CODESYS started: `method`, `ok`,
  `errors`, `warnings`, `recorded_at`. It is `null` until a build has
  finished. `cts read-log` lists that build's messages.

```sh
cts status
cts dialog           # what modal dialog is on screen right now
cts dialog answer --choose "<option>" --press OK
cts agent list       # the agents (one per IDE) on this machine
```

A modal dialog blocks the IDE, so it is worth knowing before a command is
sent: `cts dialog` reads it (it talks to the agent, which answers while the IDE
is stuck), and `cts dialog answer` chooses the options and presses a button —
`cts guide dialog` has the details.
