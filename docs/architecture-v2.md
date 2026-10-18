# Architecture v2: a thin in-process agent

Status: the C# agent is the CLI command transport and answers every IDE command itself; the IronPython daemon is gone.

## Why change

`cts` commands connect to the in-IDE C# agent, which runs them on the IDE UI
thread. This replaces the earlier IronPython-polled client pipe, which had several limits:

- the IDE pulls the CLI; the IDE can never tell the CLI anything (no events, no
  "the PLC just went online", no variable change push);
- every command pays an IronPython round trip, and the polling interval is a
  floor on latency;
- the script runs under the scripting engine, which owns the session (the
  "Executing script... CANCEL" state, the one-daemon workaround, the timer
  trick);
- the scripting API is a wrapper over the core. We reach the core only through
  that wrapper.

A live probe (kept outside this repo until now) showed a different shape works in
both 32-bit and 64-bit CODESYS with **one AnyCPU net48 DLL**:

- a script loads the DLL and returns; the DLL keeps running (own threads, a pipe
  *server* inside the IDE);
- `IEngine.InvokeInPrimaryThread` marshals any call onto the UI thread;
- `IOnlineManager` login/logout/state events can be subscribed to from the DLL;
- core services are reachable by reflection from
  `ComponentManager.Singleton.InstanceFactory.GetSystemInstance(name)`, so the
  DLL has no compile-time reference to a CODESYS assembly and does not care which
  product or version loaded it.

## Shape

```
 cts.exe (outside, net48)                   IDE process (CODESYS)
 ------------------------                   ---------------------------------
 command parsing, guides,   JSON lines      agent DLL (C#, net48, AnyCPU)
 projection, diff, fmt,     over a named    - pipe server  (one per IDE pid)
 static analysis, LLM-      pipe            - dispatcher   (-> primary thread)
 facing output              <------------>  - reflection facade (Ide, Online)
                            requests +      - event source (online, commands)
                            events
```

Principles:

1. **The agent is thin.** It exposes primitives (read/write variables, online
   state, login/logout/download, project and object access, events). Policy,
   formatting, guards and everything a user can read in `--help` stay in `cts`.
2. **No compile-time dependency on CODESYS.** Core types are found by name at
   runtime. A missing type or member is an error reply naming it, never a crash.
3. **One agent per IDE process.** An AppDomain anchor (as in the probe) replaces a
   previous instance, from any build of the DLL, when the loader runs again.
4. **Everything runs on the UI thread** unless it is pure transport.
   `InvokeInPrimaryThread` is the only door to the core. Long operations report
   progress as events instead of holding the pipe silently.
5. **The user-facing contract does not move**: `cts` commands, flags, `--json`
   shapes, `cts guide` topics and the on-disk projection format stay as they are.
   v2 is a change of plumbing.

## Transport

- Named pipe `\\.\pipe\cts-agent-<pid>`, **the agent is the server**. The CLI
  lists `cts-agent-*` pipes and asks each for a `hello` (pid, product, version,
  project path, agent version).
- Access: pipe DACL limited to the current user.
- Framing: one UTF-8 JSON object per line, in both directions.
  - request: `{"id": "...", "method": "...", "params": {...}}`
  - reply: `{"id": "...", "ok": true, "result": {...}}` or
    `{"id": "...", "ok": false, "error": {"code": "...", "message": "..."}}`
  - event (server push, no `id`): `{"event": "online.state", "data": {...}}`
  - a client may subscribe to events on a connection: `{"method": "subscribe", ...}`.
- Protocol version in `hello`; the CLI refuses an agent whose major version it
  does not know and says which side to update.
- The reply envelope (the verdict line, ISO-8601 UTC timestamps, the
  `ide-<pid> · <project>` line) is built by the CLI from the agent's replies.

## What the agent does and what `cts` does

| Area | v2 owner | Notes |
|---|---|---|
| ping, state, hello, context | agent | first vertical slice |
| online state, login/logout, download, start/stop | agent | direct `IOnlineManager`/`IOnlineApplication` |
| variable read/write/watch | agent | push on change instead of polling; write confirm logic stays in `cts` |
| online events (login, logout, state, download) | agent | forwarded as events |
| IDE command events (`ICommandManager` executing/executed) | agent | lets `cts` see user actions in the IDE |
| project export/import, object tree, POU edit | agent | `objects.*`, `project.*` |
| build, messages, PLC files and log, boot application | agent | |
| JSON test plans (`cts verify --with-test`) | agent | `test.run`, one agent call per step |
| ST tests in simulation (`cts test`) | agent | `test.app`: activate, download, read `TestResult` and the run's log, switch back |
| formatting, diff, projection, analysis, guides | `cts` | unchanged |

## Start and stop

- **One action brings up the agent.** Running `cds-text-sync` from the menu
  loads the agent DLLs and calls `AgentHost.Menu()`, which starts the agent
  unless one runs and opens the quick window. A running agent is *kept*, not
  replaced, so a second run does not drop its watches. `cts status` is the
  agent's (`project.status`). `cts install` writes that menu entry and deploys the agent (`Cts.Agent.Core.dll`, `Cts.Agent.dll`) and `cts.exe`
  into `<ScriptDir>\cds-text-sync\agent` from beside the `cts.exe` that runs it
  (the download's `dist`) or from the build tree it was built in, so there is no hand-copied DLL step.
- A tiny loader script in the user's `ScriptDir` loads the DLL, calls
  `AgentHost.Menu()` and returns. After that there is no script running, so the
  IDE is not held in "Executing script". That loader is `cds-text-sync.py`,
  which `cts install` writes.
- `cts` can start the IDE itself with `--runscript=<loader>` (not `--noUI`: the
  process exits when the script returns), so the user presses
  nothing. `cts project open --launch` does exactly that, with the installed
  `cds-text-sync.py` stub as the loader: one command on a fresh machine leaves
  the IDE and the agent ready, and it waits for the agent before it answers.
- **The agent sees the dialogs without the UI thread.**
  `dialog.probe` answers which modal dialogs are up, so `cts` refuses a command
  at once while one is open instead of waiting out the timeout.
- **A dialog is read and answered, not just reported** (`dialog.answer`, t71). The
  agent resolves the real Windows Forms control behind each caption with
  `Control.FromHandle` — the only way to tell a radio button from a push button on
  a CODESYS dialog — so the snapshot carries each option's kind and checked state,
  and the answer path can set them. The caller names options and a button; the
  agent re-reads the dialog live, refuses (clicking nothing) when a name is not
  there or the dialog's fingerprint has changed, sets the options, verifies them,
  *posts* the press to the UI thread's queue and then watches the window close, so
  a button that opens the next dialog cannot trap the call inside that dialog's
  modal loop. The hwnd is deliberately not the identity: `ModalFingerprint` hashes
  what the dialog *says*, which survives a re-created window and an IDE restart.
  (measured live against CODESYS's own login prompt.)
- A real `.plugin` that the IDE loads on its own is a possible later step; it is
  not needed for v2 and its requirements (signing, profile cache, per-version
  binding) are not yet known.
- UI entry points: one `ScriptDir` script, `cds-text-sync.py`, that loads the
  agent, also registered as a Script Command for a toolbar button; the agent's
  quick window (Alt+Q, a keyboard hook on the IDE's UI thread) holds the rest.
  Adding commands to the IDE menu at runtime is not possible through
  `ICommandManager`.

## Build, layout, tests

- `products/codesys-agent/`
  - `Cts.Agent.Core` — `netstandard2.0` (tests) and `net48`: protocol, framing,
    request queue, event bus, error model, and the `cts` commands that
    `cts.exe` and the agent share. No CODESYS names. Tested on Linux with
    `dotnet test`.
  - `Cts.Cli` — `cts.exe`, `net48`: the command line over `Cts.Agent.Core`.
  - `Cts.Agent` — `net48`, AnyCPU: pipe server, reflection facade, loader entry
    point. Builds on Linux (`Microsoft.NETFramework.ReferenceAssemblies`), runs
    only inside a Windows IDE.
  - `tests/` — protocol/transport tests; a fake core assembly that declares the
    same interface names lets the reflection facade be tested without an IDE.
  - live checks on a Windows machine per product (`tests/live/run.py`).
- The loader script ships as `cds-text-sync.py`; `cts install` writes it and
  the agent into `ScriptDir`.

## Risks

- Reflection against a moving API: mitigated by the live checks and by clear
  error replies that name the missing member.
- A bug in the agent is a bug inside the IDE process. Every dispatched call is
  wrapped, nothing is allowed to escape on the UI thread, and `Stop` must always
  work.
- A deadlock on the UI thread: calls from the pipe thread are queued with a
  timeout and the reply says which method was running.
- Antivirus or policy blocking an unsigned DLL load from `ScriptDir`: to be
  checked on a locked-down machine before release.
