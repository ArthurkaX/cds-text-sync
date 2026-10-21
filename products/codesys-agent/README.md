# codesys-agent

The in-process half of architecture v2: a thin C# agent that runs inside the CODESYS
process and talks to `cts` over a named pipe. Design:
[docs/architecture-v2.md](../../docs/architecture-v2.md).

| Path | What |
|---|---|
| `src/Cts.Agent.Core` | Wire protocol, JSON, router, sessions, event bus, UI-thread call with a deadline. No CODESYS names, no dependencies. Targets `netstandard2.0` (tests) and `net48` (the IDE). |
| `src/Cts.Agent` | `net48` AnyCPU: reflection facade over the IDE core, `IOnlineManager` event forwarding, pipe server `\\.\pipe\cts-agent-<pid>` (current user only), `AgentHost.Start`. |
| `src/Cts.Cli` | `cts.exe`, `net48`: the `cts` command line. Every command (`Cts.Agent.Core/Cli/CliCommands.cs`) talks to the agent's pipe or works on the folder alone. |
| `tests/Cts.Agent.Core.Tests` | xunit tests of the core; run on Linux. |
| `loader/agent-client.ps1` | Developer client: send one request, or listen to events. |
| `dist/` | The two DLLs and `cts.exe` prebuilt, in Git LFS: `dist\cts.exe install` deploys them, so a download needs no .NET SDK. `python tools/dist.py` rebuilds and refreshes them from the committed source, for a commit of their own: the build names the commit it came from. |
| `tools/DeadSymbols` | Lists members nothing calls (or only tests call); `allow.txt` names the ones used by reflection or the loader. |
| `tools/ApiCheck` | Pre-live check: compares the CODESYS types and statically named members used by the agent with an installation's assemblies. Missing names in `optional.txt` are deliberate probes with fallbacks. |

Build and test (Linux or Windows):

```
dotnet test tests/Cts.Agent.Core.Tests
dotnet build src/Cts.Agent -c Release
dotnet build src/Cts.Cli -c Release
dotnet run -c Release --project tools/DeadSymbols
dotnet run -c Release --project tools/ApiCheck -- <folder with CODESYS dlls>
```

Run `ApiCheck` before live testing against the CODESYS installation being tested; it reads
assembly metadata only and does not load or execute vendor code.

Dead code fails the build: an unused private member, parameter, local, assignment
or `using` is an error (`.editorconfig`). The analyzers do not see public members;
`tools/DeadSymbols` does, and exits 1 on one with no caller outside the tests.

Run (Windows): `src\Cts.Cli\bin\Release\net48\cts.exe install` copies `Cts.Agent.dll`,
`Cts.Agent.Core.dll` of the same build and `cts.exe` to `<ScriptDir>\cds-text-sync\agent` and writes
the menu entry beside them; run `cds-text-sync` from Tools > Scripting > Scripts > C > cds-text-sync,
which loads them, then `agent-client.ps1 -Method hello`.
The agent log is `%TEMP%\cts-agent.log`, shared by every IDE; each line
carries the IDE's process id in brackets.

Wire protocol: one JSON object per line. Requests `{"id","method","params"}`, replies
`{"id","ok","result"|"error"}`, pushed events `{"event","seq","time","data"}` after
`subscribe`. An error may carry optional structured detail as `error.data`. Methods so
far: `hello`, `ping`, `state`, `methods`, `subscribe`, `unsubscribe`,
`subscriptions`, `vars.read`, `vars.write`, `dialog.probe`,
`dialog.answer`, `journal.take`, `project.status`, `test.run`,
`app.start`, `app.stop`, `app.logout`, `project.syncfolder`, `project.source`, `project.simulation`, `project.credentials`,
`app.build`, `project.permissions`, `project.devices`, `project.list`, `project.open`,
`project.close`, `messages.read`, `app.bootapp`, `app.reset`, `app.crc`, `plc.info`, `plc.files`,
`plc.upload`, `plc.fetch`, `plc.remove`, `plc.mkdir`, `plc.move`, `app.download`.

`project.status` is what `cts status` shows: `{open, path, unsaved_changes,
project_id, sync_folder, suggested_sync_folder, plc: {online, application, application_state,
running}}` (`project_id` when the project has one,
`sync_folder` when this machine has its folder, `ProjectInfo.SyncFolder`, else
`suggested_sync_folder`, `ProjectInfo.Suggested`), plus `last_command: {method, ok,
errors, warnings, recorded_at}` when the last build since the agent started was of
this project.
`plc.online` is null when the IDE cannot say whether an application is logged in. It
answers while a dialog is open.

`app.start` / `app.stop` are `cts start` / `cts stop`: the IDE's Online -> Start/Stop
(`OnlineCommandHelper`) on the active application, which must already be logged in.
They answer `{state, changed, application, application_state}` once the runtime reports
the state asked for (or after 5 s); `changed` is false
when the application was already in that state. The deny list keys are `start_plc`
and `stop_plc`.

`app.bootapp` is `cts boot-app`: it stores the logged-in active application on the PLC
as its boot application (`IOnlineApplication3.CreateBootProject`), as the IDE's Online ->
Create boot application does once `OnlineCommandHelper.CanCreateBootApplication`
allows it, and refuses otherwise; `{state, application, application_state}`. The deny
list key is `create_boot_app`, denied by default.

`app.reset {kind?, force?}` is `cts reset`: `IOnlineApplication.Reset` of the logged-in
active application, as the IDE's Online -> Reset warm, cold or origin does once
`OnlineCommandHelper.CanReset` allows it, without the IDE's confirmation dialog;
`{state, kind, application, application_state}`. `kind` is `warm` (the default), `cold`
or `origin`; origin erases the application from the PLC and is refused without `force`.
The deny list key is `reset_plc`, `reset_plc --kind origin` for an origin reset, so an
entry of the latter refuses origin alone; both are denied by default.

`app.crc` is `cts plc-crc`: whether the PLC runs the code the IDE generated last,
`{application, plc: {code, data}, ide: {code, data}, match}`. `plc` is the logged-in
application's `IOnlineApplication.CodeId` / `DataId` as of the login, null when the
PLC holds no application; `ide` is `ILanguageModelManager.GetCompiledIds`, null before
any code generation; each is the id's first field, the checksum the code generator
gave it (`ICompileContext9.CheckSumCode` / `CheckSumData`), in hex. Every code
generation (download, login, online change, Generate code) gives new ids even for
unchanged source and a Compile gives none, so `match` says the PLC runs that
generation, not that it holds edits made since. `note` says why `match` is null. The
deny list key is `plc_crc`.

`app.download {start?}` is `cts download`: a full download of the active application,
the IDE's Online -> Download (`OnlineCommandHelper.Download` without online change),
which stops it and resets its variables, without a dialog. Without a session it logs in
first (`OnlineCommandHelper.LoginWithParameters`, Regular | ForceDownload with all
dialogs and error popups suppressed). `start` (default true) then starts it like
`app.start`. `{downloaded, logged_in, started, application, application_state}`;
`logged_in` says this call opened the session. The deny list key is `download`, and
`start_plc` too when it starts.

None of the `plc.*` methods logs in: each connects to the device above the active
application for its run with a share of the connection (`IOnlineDevice3.SharedConnect`,
called off the UI thread: its Begin form, like `IOnlineDevice.BeginConnect`, throws "will
(hopefully) be implemented soon"), so they work while the IDE is offline and a login stays.

`plc.info` is `cts plc info`: `{runtime, device, vendor, node, applications: [{name,
state, project, last_change, profile, compiler}]}` from `IOnlineDevice17.RuntimeSystemVersion`,
`IOnlineDevice11.GetTargetIdent` and the application lists of `IOnlineDevice6`/`8`. The
deny list key is `plc_files`.

`plc.files {path?}` is `cts plc ls`: the entries of one directory on the PLC, from the
online device's `IDirectoryFunctionService`,
`{path, files: [{name, is_directory, size, creation_time, last_write_time}], count}`
without `.` and `..`, times in UTC. `path` is a device path; `.` or none is the root,
and a Windows path (what Git Bash makes of a leading `/`) is refused. A path that is not
a directory fails. The listing is begun and ended on the UI thread with the wait between
them off it: the service completes through the UI thread. The deny list key is
`plc_files`.

`plc.upload {src, dest?}` is `cts plc put`: the file `src` of this PC (an absolute path)
written to `dest` on the PLC, the file's name in the root by default, through
`IOnlineDevice2.CreateFileDownload`; `{source, destination, size, crc32}`. It replaces a
file already there and creates missing directories. The deny list key is `plc_upload`,
denied by default.

`plc.fetch {file, output}` is `cts plc get`: the PLC file `file` saved as `output` on this
PC (an absolute path) through `IOnlineDevice2.CreateFileUpload`;
`{file, saved_to, size, crc32}`. It writes `output.cts-part` first, so a failed read
leaves an existing `output` alone; a file the PLC lacks fails with "File is not valid".
The deny list key is `plc_fetch`. Both transfers wait off the UI thread like `plc.files`,
and both compare the file with the CRC32 the PLC computes for it
(`IDirectoryFunctionService4.GetFileContentInfo`, no transfer): a difference fails, a
device that gives no CRC answers `unchecked` with the reason instead of `crc32`.

`plc.remove {path}`, `plc.mkdir {path}` and `plc.move {from, to}` are `cts plc rm`,
`mkdir` and `mv`: the directory service's `DeleteFile`/`DeleteDir` (by what the parent's
listing says `path` is), `CreateDirectory` and `RenameFile`/`RenameDir`;
`{removed, is_directory}`, `{created}`, `{from, to, is_directory}`. They answer to
`plc_upload` too.

`plc.loggers` and `plc.log {logger?}` are `cts plc-log`: the runtime's logger names
`{loggers}`, and the entries one logger holds, oldest first,
`{logger, entries: [{time, cmp_id, class, error_id, info_id, info}], count}` -- the
fields of a runtime log file line, the time in UTC and `class` the runtime's ClassId
(1 info, 2 warning, 4 error, 8 exception, 16 debug). `logger` defaults to the first
name, the runtime's standard logger; one the PLC lacks fails with the names it has.
Both come from the online device's logger service
(`IOnlineDevice3.CreateLoggerServiceHandler`), what the device editor's Log page reads,
so they work wherever the runtime writes its log file. The deny list key is `plc_log`.

`app.login {ip?, gateway?}` is `cts connect`: it logs in to the active application
without changing what the PLC runs, through the IDE's own login
(`OnlineCommandHelper.LoginWithParameters` with no flags), its questions answered
here: the online change question with "login without any change", the one to create
the application the PLC lacks with Yes (`created`), every other one (download the
changed program) with the answer that changes nothing, which ends the login.
`{state, application, reused_session, created, prompts}`;
each prompt names the question and its answer, and a refused login lists them.
`ip` first points the device at that PLC: the gateway (`gateway`, default Gateway-1)
resolves it to a router address (`IGateway2.BeginResolveBlockDriverAddress`, TCP
port 11740) and `ICommunicationSettings` takes it -- a project edit, refused while
online -- and the answer adds `{gateway, address, ip}`.  Its deny list key is
`connect_to_device`.

`app.logout` is `cts disconnect`: it logs out every logged-in application of the
project (any of them online refuses edits) and fails with "still online" when one
survives; `{state, was_connected, online_after}`, `note` when nothing was online.
Its deny list key is `disconnect_from_device`.

`project.source {source, when}` writes `cts-source` in Project Information, `<source> · <when>`, only when the label before ` · ` differs (after an import that carried everything and after `cts commit`; deny key `sync_import_text`); `project.status` answers it as `source`. `project.syncfolder {path, id, save, dry_run}` is `cts set-sync-folder`. `dry_run`
stores nothing and answers `{project_id, sync_folder, name, dry_run}`: the project's id
("" without one) and the folder `path` points to, a relative one anchored to the saved
project file, or without a path the suggested one; cts then sets up the folder's git
repository and registers it before anything is stored. The write puts `id` into the
project's `cts-project-id` property and saves when `save` is true: `{project_id,
changed, sync_folder, saved}`, with `unsaved` (and `save_error`) when a changed id is
not saved. Refused while online; its deny list key is `set_sync_folder`.

`project.list` is `cts project list`: `{projects: [{name, path, primary}], count}`, the
projects open in the IDE without the libraries it loads for them. `project.open {path}`
(`cts project open`) opens an absolute `.project` path as the primary project:
`{opened, name, already_open?}`. It refuses while another project is primary (deny key `project_open`). `project.close`
(`cts project close`, deny key `project_close`) closes the primary project: `{closed}`.
Both refuse unsaved changes, and close refuses an online session, instead of letting
the IDE ask; `project.close {discard: true}` (`cts project update`) closes with the
unsaved changes lost. The object events of a load or a close are cts's own, not the journal's.

`messages.read {category?, last?, clear?}` is `cts read-log`: the texts of one of the
IDE's message categories, oldest first, `{category: {guid, description}, count,
messages, available_categories}`. `category` is a GUID (braces and case do not matter)
or a description the IDE lists; none is Build, the compiler's. An unknown one is
refused with the list. `last` keeps the newest that many, `clear` empties the category
after the read. No project is needed; the deny list key is `read_log`.

`journal.take` answers what the IDE changed outside cts since the last take:
`{changes: [{guid, name, kinds, last}]}`, kinds `modified`, `added`, `renamed`,
`removed`, from the object manager's events. The agent's own writes are not recorded.
A `modified` object keeps the text it had at its first event and is left out when
its text is the same again (opened for edit, or typed and undone). `hello` carries
`user_changes`, the count before that check, so the CLI takes the journal only when
it is not zero.

`hello` also carries `timeout_profile` `{block_count, source, timeouts, default}`: the
budget in seconds the CLI gives each slow command, sized by the `.st` files in the
sync folder's `project-view` (counted once per folder; 600 s everywhere while there is
nothing to count).

`dialog.probe` answers the modal snapshot (`dialogs`, `epoch`) without touching the
UI thread. It is what lets `cts` say "blocked by a dialog: …" before a command
instead of a 30 s timeout, so it stays available while a modal dialog is open (it is
in `ModalGate`'s allowlist).

`test.run {folder, file?}` (`cts verify --with-test`) runs the JSON test plans of
`<folder>/.test` (`cts guide tests`) through the agent's own methods: `app.login`,
`app.reset` for a plan with `"reset": "cold"`, `app.start`, then `vars.write` and
`vars.read` per step. It holds no UI thread itself: each call takes it in turn and a
`wait` step sleeps on the pipe's thread, so the IDE stays usable while a plan waits.
A plan for another application than the active one is refused. The deny list key is
`run_tests`.

`test.app {application?, wait_ms?}` (`cts test`) runs the ST tests of a test
application in simulation: it makes that application active (`app.activate`),
downloads and starts it (`app.download`), reads `TestResult.Done` until TRUE, then
the counts and the simulation's log from the run's `CTS|M|TEST_START|` record on
(`plc.log`, as `log`), logs that application alone out (`app.logout
{application}`) and activates the earlier one again. An application on a device not
in simulation is refused. Like `test.run` it holds no UI thread and answers to
`run_tests`.

## Quick window (Alt+Q)

`QuickWidget` sets a keyboard hook on the IDE's UI thread (`WH_KEYBOARD` with
the thread's id, from `AgentHost.Start`, which the loader runs on that thread):
Alt+Q while CODESYS has the focus opens `WidgetView`, a modeless window owned
by the main window, unless a modal dialog is open. The chord is `QuickKey`:
Alt+Q, or the `quick_key` of the user's `%APPDATA%\cds-text-sync\defaults.json`
(`cts config set quick_key Ctrl+Shift+Q`), read again when a key is pressed
with a modifier and the file has changed, and matched exactly (Ctrl, Alt and
Shift as `GetKeyState` and the hook's Alt bit report them), so AltGr+Q is not
Alt+Q. With no project open, the quick window lists known projects, offers a
file picker for any `.project` file, and keeps user-level settings available.
Its rows are
`WidgetMenu.Items` for an open project and `WidgetMenu.NoProject` otherwise
(fixed digits; an item that cannot run carries the reason);
a chosen row runs `cts <command>` as a process in the sync folder with
`CTS_IDE_PID` set, and `WidgetMenu.Outcome` turns its output into the line the
window shows. Being modeless, the window never counts as a modal dialog, so the
command it runs reaches the IDE. The window shows at once; the branch is read
from git on a worker thread and filled in when it arrives, with `↑N ↓M` after
it when it has an upstream and is that far from it as last fetched
(`WidgetMenu.Where`); then the window fetches that remote quietly (`git fetch`
with no prompt, at most once a minute, given up after 30 s) and shows the counts
again when they moved, so the team's new commits show as `↓` before a pull. A
commit, push or pull reads them again, and so is the state
line under the pill: `cts compare`'s verdict through `WidgetMenu.State`
(`changed: disk N · IDE N · both N`, `in sync`, `not on disk yet — 2 writes
it` for a folder with no sync base, `state unknown` when it failed), read again after a command `WidgetMenu.MovesState` names.

Digits `1` and `2` run `cts import --tool` and `cts export --tool`: an
object both sides changed is merged. While the header's compare says both
sides changed some (`WidgetMenu.Both`), the row first runs `cts import
--dry-run --json`, whose `conflicts` carry each overlapping object's key and
both texts; with any, the quick window closes and the conflict window
(`ConflictView`, model `ConflictReview`) lists them: the chosen one side by
side, Disk wins / IDE wins / Merge by hand per object, Force for the row's
Shift run. Apply runs the row's command with `--take KEY=disk|ide` for each
side chosen and `--tool` when one goes to the merge program (`ConflictTool`). Shift with the digit or the click runs the
row's `WidgetItem.Forced` (`import --force`, `export --force`): one side
becomes the other, no merge. Digit `7` runs `cts open`: the sync folder in
the person's git program, for merging branches and the rest of git by hand;
the row says which program once `cts tool --json`, read as the window opens,
names it (`WidgetMenu.NameOpener`).

The cts runs have `CTS_PROGRESS=1`: cts writes each stage it reaches to stderr as `progress: STAGE`, which `RunCts` reads line by line and `WidgetView.Progress` puts under what runs. Opening the quick window runs a read-only `cts compare` for its state; it does not write IDE changes to the sync folder.

`MirrorRefresh` keeps that compare quick. Every 5 s it asks `IdleRefresh` (Core) whether to run one itself: the object journal's stamp moved since the last time, the person has not touched keyboard or mouse for 15 s (`GetLastInputInfo`), no cts command has been connected to the pipe for 15 s (`PipeServer.QuietMs`), and no dialog or quick-window run is up. It then runs `cts compare` in the project's sync folder through the window's runner (`QuickWidget.Refresh`), which renders the IDE objects whose TimeStamp moved (the whole project after a new cts build) onto `refs/cts/ide` and `.git/cts/ide-cache.json`; the next compare finds them there. A project without a sync folder is passed over until its objects move again.

While a command runs, the footer counts its seconds against what the last
successful run of the same kind took in this IDE session (`WidgetMenu.Kind`:
the command and its flags, not their values): `12 s of ~40 s`, and the rule
above the footer fills toward that time (`WidgetMenu.Elapsed`), waiting near
its end when the run takes longer. A kind not run yet shows the seconds alone.

Digit `3` replaces the rows with `WidgetMenu.Comparisons`: `1` the disk's
files (`cts compare --tool`), then the sync folder's local branches, read
off the UI thread like the branch list, each `cts compare --tool --against
NAME`, the one the work is on as last committed. Esc goes back to the menu.

Digit `4` replaces the rows with `WidgetMenu.Branches`: the sync folder's local
branches (`git for-each-ref`, the most recent first, read off the UI thread),
each running `cts checkout NAME --disk-only`. Only the folder moves, so the
window stays usable while online; after the run the header and the list are
read again. The branch the work is on pulls instead: `cts project update`,
offline only, on the owner's machine as on a colleague's. Esc goes back to the
menu. The list's first row, `+`, makes a new
branch where the work is.

Digit `6` is the project file's: on the owner's machine (the status says
`owner`) Commit and publish the project, `cts commit --publish -m`; on a
colleague's Pull and update the project, `cts project update`, offline only,
after which the header and the branch's distance to its upstream are read
again.

A commit (`5` or the owner's `6`) that went through asks next, when the
repository has a remote (`git remote`, off the UI thread), whether the branch
goes to the team now (`WidgetMenu.Pushing`): `1` runs `cts push`, Esc keeps it
on this PC; the branch's distance to its upstream is read again after either.
A pull (`cts project update`, from any row) asks the same when it left the
branch ahead of its upstream (`WidgetMenu.Ahead`: this PC's commits, with the
merge of the team's). A push the team's repository refused for commits the
branch lacks asks whether to pull them first (`WidgetMenu.Pulling`): `1` runs
`cts project update`, offline only, and the push question follows it.

A row with `Asks` (that row, digit `5` Commit, the owner's `6`, and a
setting) opens a one-line text box
in the footer instead of running: Enter runs the row's arguments with the
trimmed text last (`WidgetMenu.Answered`; `cts branch NAME`, `cts commit -m
TEXT`), Esc cancels. The arguments reach `cts` as one command line quoted by
`WidgetMenu.CommandLine`, so a message with blanks or quotes arrives whole.

Digit `8` replaces the rows with `WidgetMenu.Settings`: the sync folder, whose
row (`Picks`) opens Explorer's folder dialog (`FolderPicker`, IFileOpenDialog
with FOS_PICKFOLDERS) at the current folder and runs `cts set-sync-folder PATH`
(the window then opens again on the new folder); while this machine has no folder for
the project, the row offers `suggested_sync_folder`: in the dialog for a project with an
id (its folder is a clone to find), typed with the suggestion already in the line for
one without (the window of a project with no sync folder opens on this page,
its header `WidgetMenu.Unconnected`: the repository a colleague cloned by the
team's own means is picked here once), the open program from `cts tool --json` (`WidgetPage.Choices` opens a list of
installed programs; a row runs `cts tool open NAME` and settings are read again), the quick key
(`cts config show --json`, asked with the current one filled in and written by
`cts config set quick_key KEY`), then This PC (with a sync folder: owner or colleague, `WidgetPage.Choices`
rows that run `cts set-sync-folder FOLDER --owner|--colleague`, which also
sets git's skip-worktree on the project file and the pre-push hook, `TeamGuard`) and Permissions: `WidgetMenu.PermissionGroups` lists
the groups of `DenyRules.Catalog`, each a page of keys with a green
check while allowed and a red cross while the deny list in force blocks one
(`Ide.DenyList`); Space switches a
row's `Toggles` key, by the agent itself
(`Ide.TogglePermission`: `DenyRules.Toggle` writes the file through
`Json.Pretty`, Python's `json.dump(indent=2, sort_keys=True)` form, so the diff
is the key).  No pipe method and no cts command writes the list: a person
lifts a denial, an agent it refuses cannot.

Keys on every page: ↑↓ select, → opens the page a row leads to, ← and Esc
go back up one level (`WidgetView.ShowList`'s level and the action that shows
the page above), the row it was opened from selected again; Esc on the menu
closes.  The IDE takes Esc for itself before the window's own key handling, so
`QuickWidget`'s keyboard hook hands it to `WidgetView.Escape` while the window
is active.

Digit `0` opens the More page (`WidgetPage.More`): what is used now and then
stays off the menu itself, so the menu keeps to the work of every day.

On it, `1` opens `FmtView`, one per IDE: the open project's Structured Text as
the formatter would lay it out.  It runs `cts fmt --json` (the agent reads the
texts, the CLI formats them: one formatter, the analyzer's) and lists every
object, those with lines to fix marked; the one chosen shows side by side as the
IDE has it and formatted, the lines that differ marked on both sides
(`FmtReview.Changed`, a line diff that also keeps the two panes scrolled
together), with Previous/Next change (Shift+F8/F8).  Apply writes that object
(`cts fmt --guid G --write --if-timestamp T`: an object edited since the list
was read is refused) and goes on to the next one to fix; Skip goes on without
writing; Reload (F5) reads the IDE again.

`3` (`Copies`) puts `!cts --target ide-<pid> --expect-project <project>
--help` on the clipboard, for the user to paste into an AI agent's chat; its
hint names the IDE and the project.

`4` opens `FsmView`, one per IDE: the state machines in the open project's
Structured Text.  It runs `cts fsm --layout --json` (the agent reads the texts,
cts.exe finds the machines, `FsmDetector`, and lays each out as a GRAFCET
chart, `FsmGrafcet`) and lists every machine; the one chosen is drawn
(`FsmMap` holds the answer and finds what a click falls on), and a step or a
transition clicked shows the code behind it with its line.  Ctrl+wheel and
Ctrl+plus/minus zoom, Ctrl+0 fits the chart; Reload (F5) reads the IDE again.

`2` opens `ActivityView`, one per IDE: the agent's actions live. It
starts with `FileLog.Recent()` (the last lines this IDE's agent wrote) and
appends each line `FileLog.Written` raises, so the file is not read back. A
request `ActivityLog` normally leaves out is shown when it takes a second or
more, with its time; the bottom line polls `Router.Running()` and names the
request being answered.

## Answering a dialog (`dialog.answer`)

The agent is inside the process that owns the dialog, so `Control.FromHandle`
returns the *real* Windows Forms control behind each caption, and `.Checked` is
the state the user sees.  That is the only way to get it: on a CODESYS dialog
every button, radio button and check box is a `WindowsForms10.BUTTON` window
with the same owner-draw style, and `BM_GETCHECK` answers 0 for all of them.
The controls are read on the polling thread (the lookup is a handle-table
lookup, not a call into the UI thread), so `ModalWindow.Options` -- and therefore
`ui.modal.opened` and `dialog.probe` -- carry the options and
their state.

A control whose handle resolves to no .NET control (a message box drawn by the
Win32 dialog manager) is reported as a *button* rather than guessed at: it stays
pressable by name and is never listed as an option.  `ModalOption.Mark` renders
`(*)` / `( )` for a radio and `[x]` / `[ ]` for a check box, with `?` when the
state could not be read.

`dialog.answer` is the writing half.  Params:
`{"press": "<caption>", "choose": ["<caption>", ...], "uncheck": [...],
"id": "<fingerprint>", "timeout_ms": 5000}`; `press` is required.  It

1. picks the dialog by `id` (`ModalFingerprint`: a hash of the title, the text
   and the control captions, never the hwnd), or the only one open;
2. on the UI thread, re-reads the dialog live and resolves every name against
   that fresh read: a stale id, a caption that is not there, a caption that
   matches two controls, clearing a radio -- each is refused, with the fresh
   dialog in `error.data.dialogs`, **before anything is clicked**;
3. sets the options (`PerformClick` for a radio, so the group is handled the way
   a click handles it; `Checked = value` for a check box) and reads them back;
4. *posts* the press -- `Control.BeginInvoke(PerformClick)`, or `WM_COMMAND`
   (BN_CLICKED) to the dialog of a control that is not a .NET one -- and
   returns, so a handler that opens the next dialog (Clean All -> login)
   cannot trap the call inside its modal loop;
5. waits (bounded, default 5 s) for the pressed window to leave the screen, and
   reports `{answered, id, pressed, chosen, unchecked, via, closed,
   closed_after_s, covered, next}`, where `next` is the dialog that replaced
   it; a dialog that opens on top of the pressed one ends the wait at once
   (`covered=true`).

It is in `ModalGate`'s allowlist, because the state it exists for is exactly the
state the gate refuses everything else in.  Every press, and every option it
sets, is written to the agent log with the control's runtime type.

For anyone reusing this: `IButtonControl.PerformClick()` -- the recipe the
documentation suggests for driving buttons generically -- **throws
`InvalidCastException` for a `RadioButton` here** (the live control reports
`IButtonControl=False`, while `Button` reports `True`), although the framework's
reference assembly declares the interface.  `ControlReader` therefore switches on
the concrete type instead.

## Modal dialogs

While a modal dialog is open the IDE's UI thread keeps pumping, so work posted to it
runs *nested inside the dialog's modal loop*; a command that "looks busy" can therefore
already be running where it should not. The agent detects the dialog and refuses instead:

* a background watcher (`ModalWatcher`, 500 ms) enumerates the UI thread's top-level
  windows with `EnumThreadWindows` and reads their state with `InternalGetWindowText` —
  never `GetWindowText`, which sends `WM_GETTEXT` to the very thread it is diagnosing.
  A window is modal (`ModalPolicy`) when it is visible and either its owner is disabled
  or it is a `#32770` dialog that is ownerless or disabled;
* `ModalState` keeps the snapshot, a stable id per window and an epoch that moves on
  every open and every close;
* `ui.modal.opened` / `ui.modal.closed` are published with `{id,hwnd,class,title,text,
  buttons,owner,ownerless,owner_disabled,enabled,visible,at}`;
* `dialog.probe` answers `{dialogs:[...],epoch,poll_ms,poll_count}` without touching
  the UI thread; each dialog carries its options (kind and checked state) and its
  fingerprint;
* every other method whose handler needs the UI thread (`vars.read`, `vars.write`,
  `objects.write`, ...) is refused up front with `dialog_blocked`, whose message names the
  dialog and whose `error.data.dialogs` carries the snapshot. `ping`, `hello`, `state`,
  `methods`, `subscribe`/`unsubscribe`/`subscriptions`, `dialog.probe`,
  `dialog.answer` and `project.status` still answer (`ModalGate`). A call that is *already
  queued* when a dialog opens is refused too, by a modal-epoch guard inside `UiCall`;
* **the cached snapshot is confirmed before a refusal.** The snapshot is a 500 ms poll,
  so right after the user dismisses a dialog it still names the dialog that went away
  (t59 measured ~0.8 s of refusals). Before refusing, the gate (and `UiCall`'s epoch
  guard) takes one fresh look on the *calling* thread — `IModalProbe.ConfirmModal()` →
  `ModalWatcher.Refresh()`, a plain `EnumThreadWindows` poll that also updates
  `ModalState`. If it finds nothing, the snapshot was stale and the call proceeds; if
  it finds a dialog, the refusal carries the *fresh* snapshot. The confirm is not run on
  the "no dialog" path, so an ordinary call pays nothing; each poll is ~0.3 ms and
  serialized with the watcher by one lock. An epoch that moved because a dialog opened
  *and* closed while the call was queued still refuses (the call was queued in a world
  that is gone).

`UiCall` has three outcomes and says which one happened: `busy` (the UI thread never
started the call, so nothing ran), `dialog_blocked` (a dialog is up), and `timeout`
(it started but did not finish in the finish budget — the outcome is unknown, it may
still complete). A refused command names the dialog; `cts dialog` prints the dialogs.

Every request cts sends carries `project_path`, the project file its command's `hello`
named. `OnUi` checks it on the UI thread right before the work: when the IDE has
another project open by then, the call answers `project_changed` and does nothing, so
a project switched during a command (by the user or another session) is never written
to by that command. A request without `project_path` is not checked.

### What the live check measured (Windows, CODESYS 3.5.22.30)

The Win32 half was verified against the IDE on the test VM (evidence:
`codesys-re/findings/live-t59/`):

* both an IDE prompt (`engine.Frame.MessageService.Prompt`) and a WinForms
  `MessageBox.Show` are reported exactly — class `#32770`, title, body text, button
  captions, owner and enabled state; the `ui.modal.opened` / `ui.modal.closed` pair
  carries the same object and the same id;
* the snapshot is a **poll**, so it is up to `PollMs` (500 ms) stale. Before this was
  confirmed, that meant a command could be refused with `dialog_blocked` for ~0.8 s after
  the user closed a dialog (t59 §Findings 1). It is fixed (t60): a refusal now confirms
  the snapshot with one fresh `EnumThreadWindows` poll on the calling thread first, so
  the first command after a close runs — measured, **0–9 ms** after the close in 5/5
  rounds, one attempt each, while a call made *with the dialog up* is still refused;
* a WinForms `MessageBox.Show(text)` with no explicit owner produces an **ownerless**
  `#32770`. It is caught by the `ownerless` rule, not by the disabled-owner rule — the
  owner-disabled signal alone does not see it;
* the ordinary top-level windows — the main frame and cts's own WinForms forms —
  are not `#32770` and are not flagged, so normal operation produces no modal event;
* the watcher's poll never failed once in the session (`modal poll failed`: 0); it
  reads the UI thread id directly in `Start` (which runs on that thread), so the
  first poll is already aimed at the right thread. (Older builds posted a probe to
  the UI thread from `Start`, which could not run until `Start` returned and so
  timed out after 5 s; that probe is gone.)
* **ordering.** A single connection is serialized: the session serves one request to
  completion before it reads the next, so pipelining on one connection gives strict
  request/reply order. Requests on *different* connections reach the UI thread in an
  order that is **not** the submission order (measured: three calls sent Z, A, B ran
  Z, B, A). Cross-connection ordering must not be relied on.

## Variables (`vars.*`)

Reading and writing a PLC variable: the chain is
`ILanguageModelManager.GetVarReference(guid, expr)` -> `IOnlineManager.CreateWatch` ->
`IOnlineVarRef.Value` / `.State`, and a write sets `IOnlineVarRef.PreparedValue` then
calls `IOnlineApplication.WriteVariables([watch])`. Everything runs on the UI thread
with the start deadline every UI call has (`start_timeout_ms`, default 10 s): a
call the UI thread does not start in time answers `busy` and never runs late.

| Method | Params | Answers |
|---|---|---|
| `vars.read` | `{"names": [...], "app"?: "<name\|guid>", "start_timeout_ms"?}` | `{"online", "logged_in", "application", "results": [{"name","ok","value","type","iec","state","text"?}]}` |
| `vars.write` | `{"values": {"name": value, ...}, "app"?, "start_timeout_ms"?}` | `{"online", "logged_in", "application", "results": [{"name","ok","written","value","text"?}], "written": n}` |

`app` defaults to the project's `ActiveApplication`; a name is resolved with
`GetApplicationGuidByName`. A read `value` is a JSON scalar (bool, integer, real,
string). A struct or an array is not one value: its name fails with `not_scalar`, and
its members or elements are read one by one.
`iec` is the expression's IEC type name (`WORD`, `INT`, `STRING(40)`, ...), read once
per watch from `IVarRef.WatchExpression.Type`, and `null` when the IDE gave none.
`state` is the IDE's own state text (`Good`, `NotLoggedIn`, `NotMonitoredYet`, ...).
`text` is the value as the IDE spells it -- `WORD#5`, `REAL#1E-05`, `TRUE`, `'it$'s'`,
`E_Mode.Run` -- from its own literal converter
(`ILanguageModelManager.GetConverterToIEC`, full type prefixes, decimal), the same
spelling its scripting `read_value` prints. The CLR value cannot give it: it does not
tell `WORD` from `UINT`, and a REAL's digits come from the IDE runtime's formatting.
One bad name never fails the call: it carries `ok: false`, its `state` and an `error`
object whose `code` is `bad_params`, `not_exported`, `not_scalar`, `read_failed`,
`write_failed` or `unknown_application`.

A write takes a JSON string as an IEC literal for the variable's type, parsed by the
IDE's own converter (`GetConverterFromIEC().GetLiteralValue`): `5`, `16#FF`,
`WORD#7`, `REAL#2.25`, `1e-5`, `TRUE`, `T#2s`, `'text'`. A STRING also takes bare
text as its content; an enum takes its member as `E_Mode.Run`, `Run` or
`E_Mode#Run`. What the converter and the IDE both refuse fails with `write_failed`
and the IDE's reason. A JSON bool or number is converted to the variable's CLR type
(the one the last read of that watch returned; without one, the natural CLR type of
the JSON scalar); a value that type cannot hold is refused with `bad_params`, never
coerced. `null`, an array and an object are refused the same way. A write answers
to the project's deny list under the key `write_variable` (allowed by
default) and is refused whole with `forbidden` when it is denied. A write does not
read back; the caller decides, and the result's `text` is the written value as the
IDE spells it (`hello` -> `'hello'`, `16#FF` -> `WORD#255`), what a read-back shows
once the write took effect.

Watches are cached per `(application, expression)`, so a repeated read costs one hop
to the UI thread. The cache is dropped on any login, logout or download event (the IDE
warns that watches built before a download answer "Invalid expression" afterwards) and
when the `ActiveApplication` changes. It is bounded (1024 entries, oldest first).

## Object fields (`objects.fields`, `objects.setfield`)

An object's persisted fields are its `IArchivable` tree — `SerializableValueNames`
and `Get`/`SetSerializableValue`, the names and the tree the CompactXml archive
carries. It is how cts reads what is not text: a task's priority, a text list's
rows, a device's IO mapping.

| Method | Params | Answers |
|---|---|---|
| `objects.fields` | `{"guid", "prop"?, "depth"?}` | `{"guid", "name", "type", "fields", "prop"?}` |
| `objects.setfield` | `{"guid", "path", "value", "prop"?}` | `{"guid", "old", "value", "created"?}` |

`fields` is JSON all the way down: a scalar (string, primitive, enum by name,
Guid) as its text, a nested archivable as an object of its own fields, a hashtable
as `{key: value}`, any other collection as an array. `depth` (default 4, capped at
32) is how many levels are expanded; a node at that limit is present but empty,
the way `project.tree` answers at its own depth. Two kinds of member are left out:
the text (a POU's `Interface`/`Implementation`, a visualization's own
`TextDocument` — that is the body, which the `.st`/`.xml` projections carry), and
what CODESYS regenerates on every save (`UniqueIdGenerator`, the guid
init/reinit/exit members, `LineInfoPersistence`, `LanguageModelData`). `prop`
(`BuildProperty`, `SVFoldersProperty`) reads one of the meta object's properties
instead of the object; an unknown guid, or an unknown property, is `bad_params`
with the ones the object has.

`setfield` walks a dotted path with list indices — `Watchdog.Time.Time`,
`TextList[0].LanguageTexts[0]` — and writes `value` as the type of the field it
replaces: a string field takes it as it is, an enum by name (`Cyclic`), a Guid by
its text, anything else in the invariant spelling of its type. A path the object
does not have, a value its type cannot hold (including one out of range), or a
length no list has is `bad_params` and writes nothing; the answer's `old` and
`value` are read from the object around the write, so `value` is what the IDE
actually holds. When `prop` names a meta property the object does not have yet,
the write creates it first — the way the IDE adds a `BuildProperty` when you set
"Exclude from build" on any POU — instantiates the loaded `IObjectProperty` type
of that name, `AddProperty`s it and commits in the same write; the answer then
carries `created: true`. A `prop` that names no property and no loaded property
type is `bad_params` naming it. The write commits through `SetObject` and is
refused while an application of the project is logged in — the running
application keeps the old symbols until the next download. If the online question cannot be
answered, the write is refused too.

## Object texts (`objects.text`, `objects.texts`)

`objects.text {guid}` reads one object's declaration and implementation in
about 10 ms. `objects.texts` is the bulk read that makes a disk<->IDE check
cheap without a whole-project export: one call returns every text object.

| Method | Params | Answers |
|---|---|---|
| `objects.text` | `{"guid"}` | `{"guid", "name", "type", "timestamp", "declaration", "implementation"}` |
| `objects.texts` | `{"guids"?, "start_timeout_ms"?}` | `{"objects": [{...}], "count", "ms"}` |

Without `guids`, `objects.texts` walks every object of the primary project and
keeps the ones that have an `Interface` and/or `Implementation` text document
(a POU, method, action, property accessor, GVL, DUT, interface); an object whose
both parts are absent — a graphical body, a task, a device — is not a text
object and is left out. Each record has the shape `objects.text` returns. A
`guid` that is not one, or an object that is not there, is `bad_params`.

`ms` is the wall time the call spent inside the IDE — one
walk of a 669-object project measured about 12 ms. Runs on the UI thread like
`objects.text`, with the same `start_timeout_ms` (default 10 s) as the other
long calls. The language model of a `VisualManagerObject` is never read.

An editor keeps the edit of the line its caret is on to itself until the caret
leaves the line. Before every `objects.*`, `journal.*`, `project.export`,
`project.save`, `app.build`, `app.download` and `app.login` call
(`OpenEditors.CommitFirst`) the agent has each open editor give its text to its
object (`IFrame.GetEditorViews()`, `IEditor.Save(true)`), outside the journal's
`Own`, so the edit is recorded as the user's.

## Quick window drive (`widget.*`, Debug build only)

`dotnet build src/Cts.Agent -c Debug` builds an agent with two more methods, for
tests of the quick window itself; the Release DLL, the one a download installs,
has neither:

| Method | What |
|---|---|
| `widget.snapshot {}` | what the window shows: `open`, `branch`, `commit`, `state`, `place`, `level`, `rows` (`key`, `label`, `hint`, `enabled`, `blocked`, `selected`, `current`), `footer`, `ok`, `running`, `busy`, `asking`/`typed` (a row's line), `copy` (the Copy link of a failure), `trail` (rows chosen), `comparing`, `dialog`. |
| `widget.drive {steps, timeout_ms?}` | the steps in order, each on the UI thread through the handlers a key or a click reaches (window focus does not matter), then waits until the window is idle (no run, no compare, the same for a few polls) and answers the snapshot with `idle` and, after a `copy` or `ctrl+c`, `clipboard`. |

Steps: `open` (then waits until idle: the window greys its rows while its first compare runs), `close`, a key (`1`..`9`, `0`, `+`, a letter), `enter`, `esc`, `left`, `right`, `up`,
`down`, `space`, `backspace`, `f4`, `pgup`, `pgdn`, `ctrl+c`, `type:TEXT` (into the line a row
asks for), `copy` (the Copy link), `wait:MS`, `idle`. Example:
`{"method": "widget.drive", "params": {"steps": ["open", "5", "1", "type:try-this", "enter"]}}`.
A step that opens a dialog (a question box, the folder dialog) answers with `dialog: true`;
`dialog.probe` and `dialog.answer` take it from there.

## Developer tools (`dev.*`)

Loader option `CTS_AGENT_OPTIONS=dev` (comma-separated, next to `no-events` and
`enrich`) registers methods that are otherwise absent. They exist to discover
the IDE's own API from a *live* process — the vendor DLLs are never decompiled:

| Method | What |
|---|---|
| `dev.reflect {root, path?, members?, max_members?, max_items?, timeout_ms?}` | walk an object graph and describe the node: runtime type, interfaces, ToString, and with `members` its members (vendor namespaces first). An enum lists its literals with their values (`PromptResult.OK = 0`). A collection previews its first 20 items, or `max_items` (up to 2000). |
| `dev.pin {root, path?}` | keep an object (`-> n`) so later calls can start from `pinned:<n>`. |
| `dev.listen {root, path?, event}` | subscribe to any event of any delegate type; each raise publishes `dev.event` with `{id, event, thread, sender_type, args: {type, properties}}`. |
| `dev.unlisten {id}` | drop one listener. Every listener is removed when the agent stops. |
| `dev.types {pattern}` | the loaded types whose full name matches the regex, with their assembly (at most 500, `truncated` beyond): where an API lives before there is an object to reflect on. |

`root` is `engine`, `online_manager`, `system:<interface full name>`,
`static:<type full name>` or `pinned:<n>`. A path step is `Prop` (read), `Prop = <value>`
(write), `Method(a, b)`, or `[n]` (the n-th element of an IEnumerable); an argument is
`"text"`, `<guid>`, `<int>`, `<true|false>`, `<null>`, `pinned:<n>` (an object kept by `dev.pin`,
so a walked object can be passed on) or `[a, b, ...]` for the methods that take an
array. Every step runs on the UI thread with its own deadline; a missing member is an
error that names it and lists close names. The walker, path parser, describer and
expression-built event handler live in `Cts.Agent.Core` and are tested against ordinary
.NET objects.

`cts read` and `cts write` are served by `vars.*` above. The CLI sends the user's
text and shows the agent's `text`, both in the IDE's own literal spelling.
