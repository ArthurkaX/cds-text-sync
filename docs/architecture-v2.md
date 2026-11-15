# Architecture: cts.exe and the in-IDE agent

Status: current. `cts.exe` runs every command in its own process; a C# agent
loaded into the CODESYS process gives it the IDE over a named pipe and carries
the in-IDE windows. Both are built on one shared library, `Cts.Agent.Core`.
The IronPython daemon of earlier releases is gone.

## Assemblies

Source: `products/codesys-agent/src`.

| Assembly | Target | Runs in | Holds |
|---|---|---|---|
| `Cts.Agent.Core.dll` | `netstandard2.0`, `net48` | `cts.exe` and the IDE | every `cts` command (namespace `Cts.Cli`), export/import/compare planning, git, the analysis rules, visu, docs and diagrams, trend, FSM detection and layout, the formatter, the guides (embedded resources); and what both processes share: the wire protocol, router, sessions, event bus, the UI-thread call with a deadline, the modal policy, the deny list, the quick window's menu and review models |
| `cts.exe` (`Cts.Cli`) | `net48` | its own process | `Program.cs` only: console encoding and pipe discovery (`PipeHost`); the rest is Core |
| `Cts.Agent.dll` | `net48`, AnyCPU | the IDE process | the `Ide` reflection facade over the CODESYS API, the pipe server, IDE events, the modal watcher and dialog answering, the in-IDE windows, `CtsRunner` |

Core references neither a CODESYS assembly nor `System.Windows.Forms`;
`Cts.Agent` is the only assembly that uses either.

## cts.exe

`Program.Main` sets up the output encoding and calls `CliRun.Run` with the
command `CliCommands.Find` picked and a `PipeHost`, which lists the
`\\.\pipe\cts-agent-<pid>` pipes and opens one. Parsing, help, choosing the
agent, the command itself, the verdict line and `--json` are Core code running
in the `cts.exe` process. Each command is a `CliCommand`:

- A **local** command (`LocalExecute`: analysis, docs and diagrams, visu,
  trend, git and merge, install, `project open --launch`, ...) works on the
  folder and never opens a pipe.
- Any other picks an agent (`AgentChoice`: the one `--target` names, else the
  only one, else the one whose sync folder holds the work folder;
  `CTS_IDE_PID` narrows it to one IDE), reads its `hello`, and runs `Execute`
  with a `CliCall`. `CliCall.Call` sends one request over the
  `AgentConnection` within the command's budget (sized from the hello's
  `timeout_profile`) and turns an error reply into the command's failure.
- A command that writes a sync folder takes that folder's lock (`FolderLock`)
  in `cts.exe`; two commands on one folder run one after the other.

Export, import and compare are planned in `cts.exe`. Export asks the agent for
the IDE's snapshot (`project.export`, written per object with
`IObjectManager2.ExportObject`), then writes the view and advances cts'
private base itself. Import reads the disk, the base and the IDE's objects
(`objects.export`, `objects.texts`, `project.tree`), plans in `ImportPlanner`,
and applies the plan through the agent's primitives (`objects.settext`,
`objects.replace`, `objects.create`, `objects.import`, `objects.delete`,
`objects.move`, `objects.rename`, `objects.setfield`, `project.save`). Git runs
as a child process of `cts.exe` (`GitRun`).

## Transport

- Named pipe `\\.\pipe\cts-agent-<pid>`, one per IDE; **the agent is the
  server**. The pipe's ACL admits only the user that runs the IDE. Overlapped
  I/O, so a pushed event is not held behind a pending read.
- One UTF-8 JSON object per line, in both directions (`Protocol.cs`):
  - request `{"id", "method", "params"}`
  - reply `{"id", "ok": true, "result"}` or `{"id", "ok": false, "error": {"code", "message", "data"?}}`
  - event `{"event", "seq", "time", "data"}`, pushed only to a connection that
    sent `subscribe`; a writer thread with a bounded queue sends them, so a
    client that stops reading never blocks the IDE.
- `hello` carries the protocol version, the agent's build, the pid, the
  product, the open project and the timeout profile. `cts.exe` refuses an
  agent whose protocol major differs, and warns when the agent is another
  build than itself.
- Each request names the project its command began with; the agent refuses
  (`project_changed`) when the IDE has another one open by then.

## The agent

**Start.** `cts install` writes the menu stub `cds-text-sync.py` into the
ScriptDir (and the same entry as a Script Command for a toolbar button). The
stub loads the agent DLLs and calls `AgentHost.Menu()`, which starts the agent
unless one runs in this IDE and opens the quick window. `AgentHost.Start`
replaces an agent of any build it finds under the AppDomain anchor. The script
returns at once; the agent keeps running on its own threads (online and object
events, modal watcher, pipe server, quick window, mirror refresh), so the IDE
is not held in "Executing script". `cts project open --launch` starts the IDE
with `--runscript=<stub>` and waits until its agent answers.

**Reflection facade.** `Ide` (a partial class over `Ide.cs`, `IdeManager.cs`,
`IdeReflection.cs`, `Objects.cs`, `Export.cs` and others) finds every CODESYS
type by name at run time; core services come from the component manager's
system instances. The DLL has no compile-time reference to a CODESYS assembly,
so one AnyCPU build runs in 32-bit and 64-bit IDEs, and a member a version
lacks is an `unavailable` reply naming it, not a crash.

**Methods** (`Router.Register`): `hello`, `ping`, `state`, `methods`,
`subscribe`; `objects.*` and `project.*` (tree, texts, export, edits, open,
close, save, devices, sync folder, simulation, credentials, permissions);
`app.*` (build, login, logout, download, start, stop, reset, boot application,
CRC, scan); `vars.read`, `vars.write`; `plc.*` (files, log); `messages.read`;
`trace.*`; `dialog.probe`, `dialog.answer`; `journal.take`; `test.run` (JSON
test plans, each step one of the agent's own methods) and `test.app` (ST tests
in simulation); `widget.drive`, `widget.snapshot` (the quick window driven by
a test); `dev.*` only when enabled.

**Events.** `IOnlineManager` events become `online.*` events, the modal
watcher's `ui.modal.opened` / `ui.modal.closed`. `IObjectManager` events feed
the object journal: after each command `cts` names what the IDE changed outside
it since the last one (`journal.take`).

**Dialogs.** The modal watcher polls the IDE process's top-level windows every
500 ms. While a modal dialog is up, the router's gate answers only the
UI-free methods and refuses the rest with `dialog_blocked`, after one fresh
look so a dialog just closed does not refuse the next command.
`dialog.answer` resolves the real Windows Forms controls behind a dialog
(`Control.FromHandle`), checks the caller's names against a live read and the
dialog's fingerprint (what it says, not its hwnd), sets the options, verifies
them, posts the press and watches the window close.

**Policy the agent enforces.** Whatever client sends the request:

- the deny list (`DenyRules`, from the sync folder's `cds-text-sync.json`;
  an unreadable file refuses every gated method). Each write method has a
  fixed key (`DenyRules.KeyFor`), so a client cannot route a write through a
  weaker one; the handler checks it before it edits;
- no edits while any application of the project is logged in;
- the project a request began with (above).

Everything else a command decides (what to import, how to merge, what to
print) is decided in `cts.exe`.

## In-IDE windows

The windows are product features, not a debugging aid: the quick window
(Alt+Q by default, a keyboard hook on the IDE's UI thread, not a global hotkey),
the conflict window, the format review, the FSM view (live while logged in),
the analysis window and the activity window. Except the activity window (the
agent's own log) and the permission switches (the agent rewrites the deny list
with `DenyRules.Toggle`), each action is a `cts.exe` run: `CtsRunner` starts
the `cts.exe` deployed beside the agent, off the UI thread, with `CTS_IDE_PID`
so it targets this IDE and `CTS_PROGRESS` so it names its stages. The tool
windows draw what `cts fmt --json`, `cts fsm --layout --json` or `cts analyze`
answer, and apply through `cts` as well. `MirrorRefresh` runs `cts compare`
while nobody works, so the quick window opens on a current picture. The logic
stays in `cts`, and a person sees the verdict line a script reads.

## Threads

From the code's comments, the places that are threading-sensitive:

- **UI thread.** Every call into the core goes through `Ide.OnUi` and
  `UiCall.Run`: it posts with `IEngine.InvokeInPrimaryThread` in asynchronous
  mode and waits with a deadline. `busy` means it never started and never
  will (an abandoned call does nothing when the UI thread reaches it),
  `dialog_blocked` that a modal dialog was up, `timeout` that it started and
  did not finish in time.
- **Online events** (`OnlineEvents`) are raised inside the IDE's own
  operations, often off the UI thread with its locks held: a handler reads the
  arguments and queues, and never calls back into the IDE; the optional
  application state is asked later from a pool thread, with a deadline.
- **Object events** (`ObjectEvents`) feed the journal; a handler reads the
  object's kind and, on an object's first change, its text before the edit.
- **Window reads** (`ModalWatcher`, `Win32`) never send a message to the UI
  thread (`InternalGetWindowText`, not `GetWindowText`), so they work while it
  is inside a modal loop; the one message is a posted click, never a sent one.
- **Device services** (`PlcFiles.OnDevice`): Begin on the UI thread, wait off
  it, End on it again; the services complete through the UI thread, so an End
  waiting there never returns. The shared device connection is taken off the
  UI thread.

## Why these boundaries

- **One Core, two hosts.** `cts.exe` and the agent share the protocol, the
  deny list and the menu and review models from one assembly, so they cannot
  drift apart within a build. Without CODESYS or Windows Forms references it is
  tested on `net10.0` (`tests/Cts.Agent.Core.Tests`, xunit) with no IDE; the
  commands run there against a fake agent host.
- **Commands in `cts.exe`.** A command is the same whether a script or the
  quick window runs it. `net48`, so a PC that runs CODESYS needs no extra
  runtime.
- **The agent holds what needs the IDE process**: reflection over the core,
  the UI thread, the events, the dialogs' controls, and the windows a person
  uses there.
- **Enforcement in the agent**: the pipe is the door to the IDE, so the deny
  list and the online refusal hold for any client of it.

## Deploy and test

- `cts install` copies `Cts.Agent.Core.dll`, `Cts.Agent.dll`, `cts.exe` and
  `cts.exe.config` into `<ScriptDir>\cds-text-sync\agent`, from beside the
  `cts.exe` that runs it or from its build tree. `cts.exe` goes with the agent
  so the quick window runs the same build.
- `Cts.Agent` has no unit tests: `tools/ApiCheck` compares the CODESYS types
  and members it names with an installation's assemblies, and
  `tests/live/run.py` runs live scenarios against an IDE.

## Risks

- Reflection against a moving API: mitigated by `ApiCheck`, the live checks
  and error replies that name the missing member.
- A bug in the agent is a bug inside the IDE process: every dispatched call is
  wrapped, a handler fault becomes an `internal` reply, and `Stop` stops each
  part whether or not another failed.
- A stuck UI thread: the deadline and the abandoned-call rule above; the reply
  says which method was running.
- An unsigned DLL loaded from the ScriptDir may be blocked by antivirus or
  policy on a locked-down machine.
