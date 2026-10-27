# Changelog

All notable changes to this project will be documented in this file.

---

### Unreleased

**Feedback**

- `cts diag` prints what a bug report needs: the cts, Windows and git versions, whether the CODESYS menu entry is up to date, the IDEs with an agent and the sync folder's git state as settings and counts. It names no file, object, branch, project or path.
- The quick window's More > `6` Report a problem makes a report for a GitHub issue or the Discord server: `cts diag`, the failure shown and this IDE session's cts runs and agent errors, with the names the agent knows, paths and quoted text replaced. It goes onto the clipboard and into a text file to read before sending. The link under a failure is now Report and makes the same report; it no longer copies the run's whole output with names.

---

### Version 4.0.0 (2026-10-26)

_What changes against 4.0.0-beta.3. Coming from 3.4: [docs/upgrade-4.md](docs/upgrade-4.md) is the short version, the three beta sections below are the whole of it._

**Upgrading: what changes**

- The sync folder's `.gitattributes` keeps every file as written (`* -text`). Before, on a PC whose git converts line endings (`core.autocrlf true`, Git for Windows' default), git listed the files an export wrote as changed though their content was the same. `cts set-sync-folder` adds the line to an existing repository and gives the files git checked out with CRLF their LF back; the quick window offers that once an IDE session where git converts them. Commit `.gitattributes` so every PC of the team gets it.

**Sync**

- An import is refused before it writes anything when an object it would change was edited in the IDE after its plan read it (an edit made while a merge window was open, say); run it again to carry the edit.
- A view file is written to a file beside it that then replaces it, so a write cut short leaves the old file whole (`~cts-*.tmp`, which the sync folder's `.gitignore` names).

**Agent**

- A start that fails part way stops what it started, and a stop stops every part though one fails, naming the failed ones.

---

### Version 4.0.0-beta.3 (2026-10-23)

_What changes against 4.0.0-beta.2._

**Upgrading: what changes**

- An entry's `Path` in a native `.xml` file holds its ancestors' object names, not the labels the IDE shows (`Plc Logic`, not `PLC Logic`), so a file reads the same from every PC. The first `cts export` after the update rewrites `Path` in the native files of a repository exported where the two differ: a one-time diff to commit, with no change to the objects. `cts compare` leaves `Path` out of a native file's content, so a file another PC wrote with other labels is unchanged, not a modified one an import replaces or refuses.
- A project's files never carry its id: `Project Information.xml` leaves `cts-project-id` out as it does `cts-source`, so the first export after the update drops that entry from it. Importing a copied folder no longer gives the copy the original's id, and `cts set-sync-folder --new-id` takes a copied folder whose `cds-text-sync.json` still names the project.
- `cts plc-log`, `cts plc get` and `cts test` take the file to save as `--out PATH`, as `cts docs` does; `--output` is only the answer's format.

**Sync and merge**

- Objects whose edits on disk and in the IDE overlap open a conflict window from the quick window's `1` and `2`: it lists them, shows one side by side with the differing lines marked, and takes Disk wins, IDE wins or Merge by hand for each, or Force for all. `cts import`, `cts sync` and `cts export` take `--take [KEY=]disk|ide`, repeatable, for one object's side or every one's.
- A text list or an `.xml` object both sides changed is merged; an overlap is a conflict carrying both texts, which `--take` settles and the conflict window shows.
- A removed and an added object whose texts are alike are one rename: the object keeps its GUID, and its members move with it (one at its old place keeps its GUID and takes the new text, one it lost is deleted, a new one is made below it).
- The IDE's tree is keyed by the names its files carry, so an object named `A/B` is found under `A_B`, not refused as not in the IDE; a changed native object whose file has a `__<guid>` suffix is found by its GUID when a sibling has its name.
- A new native object at the view's top, or a project-level one in `POUs/`, goes to the project root. A plain folder whose directory left the disk with its objects is deleted, and one whose directory a move left empty goes with its objects.
- An import or sync gives the sync base every file the disk and the IDE already agree on, so `cts build` no longer names such a file as not imported after every sync; a file only moved since the base is not named either. `cts import --dry-run` lists the folders the import would delete.
- A project file older than the folder (saved before the last import, or a pull came since) is brought up to date, not taken for IDE edits, and `cts status` says how many commits it is behind.
- A view read that fails is tried once more, then named as `read_failed` with its file, not refused.
- A task call whose ObjectTypeGuid is empty (V3.5 SP20 Patch 1) is known by its class: the view leaves it out, and the calls a load adds are no IDE edit.

**PLC and tests**

- `cts download --online-change` changes the running application, logging in unchanged first; a change only a download can carry is refused.
- `cts test` ends its wait on an exception, a stop or reads that stop answering, and quotes the exception; it names a boot application made on download. `--repeat N` counts every run in `passed=` and `failed=` (`per_run=` is one run's tests). `cts plc-log` hints at known runtime lines.
- `cts read` expands a name deep in a path (`fb.array`) by its own type, an `ARRAY OF STRING(n)` to its elements.
- `cts raw` sends a value like a GUID that starts as an out-of-range number as a string; a create into a folder names the folder (`folder_guid`).

**Libraries, build and analysis**

- `cts lib add` takes the library's own namespace and `--placeholder` references it through a placeholder (a project with no Library Manager gets one at its root); `cts lib redirect` fixes a placeholder's version; a reference to version `*` names the newest version installed on this PC.
- `cts build` and `cts docs --show` name the installed library that holds an unknown name, including libraries installed after the IDE started. `cts docs` says of a library with no pages whether its comments are plain text or its pages are not written yet.
- New `cts project new` makes an empty project or library from the installation's template, with no IDE.
- `cts analyze` reports fewer false findings (CTS0015, CTS0035, CTS0047, CTS0050, CTS0051, CTS0091) and takes `--severity danger|suspicious|style` to keep only findings that severe or worse; new CTS0101: a `///` comment after a declaration documents the one below it.

**Answers**

- `cts verify --json` carries every problem of a stage (the text answer still shows the first 20 and names the rest); `cts new` and `cts verify` name their next commands as `Next:` lines, as the other commands do, and `cts new` prints its note.
- `cts status` no longer promises an import when `cts compare` finds nothing to bring in; `cts compare` without a sync base says its counts cannot tell which side changed.
- A command run inside another sync folder than the IDE project's warns and names the folder it works on. `cts agent list` names the `cts dialog answer` line for an IDE a dialog blocks.

**Install**

- `cts install` updates and checks every ScriptDir that holds an install, held files included; the warning about an agent of another build names the IDE's ScriptDir.
- The setup archive leaves out the tests, whose paths passed Windows' 260-character limit when setup unpacked a commit from `main`.

---

### Version 4.0.0-beta.2 (2026-10-20)

_What changes against 4.0.0-beta.1._

**Upgrading: what changes**

- The built-in deny list no longer has `delete_pou`: deleting all of an object's files deletes it in the IDE unless the project denies that key, and a denied delete refuses the whole import, which the refusal says.
- `cts commit` and the quick window's `5` Commit the disk and `6` Commit the disk, publish commit the folder as it is on disk, not the IDE; they warn when the IDE differs, and the message prompt counts the IDE edits `2` IDE -> Disk would carry first.

**Sync**

- Folders of the POUs tab work like the folders below an application: export writes `<Folder>/.cds-object.xml` with its objects inside (before, they landed at the root of `project-view/`), and import creates objects and folders in them and moves objects between them. A new folder at the root of `project-view/` goes to the POUs tab, and an object moves between the POUs and the Devices tab and to the root of `project-view/` both ways. A folder renamed on disk or in the IDE keeps its GUID; `cts sync` removes a folder the IDE deleted with its files, and `import --force` brings a folder and its objects the IDE deleted back from disk. An IDE body added to an object whose `.st` had no `// --- implementation ---` line reaches the file.
- An object goes into the folder of its parents' names even where CODESYS records other labels for them (a project a script made: a task configuration named `TaskConfiguration`, labelled `Task Configuration`, below `Plc Logic`, labelled `PLC Logic`), so its files no longer split into two folders that differ in case or spacing. `cts compare` names folders git tracks in two spellings that differ only in case, which Windows holds as one.
- A view file changed on disk while `cts import`, `cts export` or `cts sync` runs (by an editor or another program; cts commands wait for each other) is not overwritten, and its sync base does not take that change: the answer names it (`changed_meanwhile`) and the next `cts compare` shows it. A new file whose object the IDE did not take (`unapplied`) stays out of the sync base, so the next sync carries it again instead of taking the IDE's side.
- An object, text list or save the agent refuses during `cts import` or `cts sync` is named (`unapplied`, `save_error`) and the rest still lands and is answered; a call with no reply in time or over a broken connection ends the command, its outcome unknown, and the answer says the IDE may hold part of the changes: `cts compare` shows what still differs and running the command again carries the rest.
- `cts import` and `cts sync` of several large screens read every one back; before, a screen past the agent's first reply was reported `unapplied` though it had landed.
- `cts compare` names an ignored file the IDE holds otherwise than the disk, and `cts import --include-ignored PATH` carries one; its sync base then takes the file, so carrying it back later works the same way.
- An XML object saved by one CODESYS version and exported by another (an SP16 Library Manager opened in SP22, which writes an unset field as `<Null>` where SP16 wrote an empty `<Array>` and adds empty fields) compares unchanged.
- A folder on a mapped network drive, a `subst` drive or behind a link is the repository's root when git's own root is (git names it by its UNC path or target). `cts set-sync-folder` without a path offers the git repository a project lies in, where a folder beside the project inside that repository was always refused.

**IDE, PLC and dialogs**

- Every call of a command names the project it began with, and the agent refuses it (`project_changed`, nothing done) once the IDE has another project open. With a copy of the project open in a second IDE, a command without `--target` names both project files and `CTS_TARGET`.
- A question the IDE showed and closed again while a command ran is named under its line (`dialog seen meanwhile`, `dialogs_seen` in `--json`). `cts project open` names a dialog the load leaves on screen (Project Environment) with its answer line, `cts agent list` names the dialog an IDE is blocked by, and `cts project open --launch` refuses at once in session 0.
- `cts project close --save|--discard --quit` closes the project and exits CODESYS; the refusal for unsaved changes names `--save` and `--discard`.
- `cts reset` answers once the application has stopped, so a `cts start` right after it starts the application; a reset the deny list refuses points to the download it allows.
- `cts write` confirms a number only when the read-back is the value written: a whole number exactly, a REAL as one float, any other number as one double.
- `cts connect` and `cts download` say under their line that the IDE stays online. `cts download` and `cts test` say `saved=by-ide` when CODESYS saved the project on its own while they ran; in a repository with no commit yet, `cts download` says that, not each uncommitted file.
- `cts plc-log --tail 0` prints every entry. `cts project device-types` names `--filter` first when its list is long.

**Tests and build**

- `cts test --plc` runs the tests on the device's PLC, and `--repeat N` runs them N times (a warm reset between runs when the deny list allows it) and names each failing test with its run. Each run waits for its own records, which reach the runtime's log a moment after `TestResult.Done`; a run whose `TEST_START` does not come did not run and fails.
- `cts build --all-objects` marks the messages of objects no task calls `not called by any task` (`not_called` in `--json`); errors that name an unknown type or identifier come with the namespaces of the libraries the Library Manager references qualified-only.

**Libraries and docs**

- New `cts lib` lists the library references, and `cts lib set --qualified-only`, `lib add` and `lib remove` change them on disk for `cts import`.
- `cts docs --show NAME` prints one library symbol (`Standard.TON`, `NBS.TCP_Client`) without writing the bundle.

---

### Version 4.0.0-beta.1 (2026-10-18)

_What changes against the 3.4 releases, by area; the step-by-step history is in `git log`. The short version is [docs/upgrade-4.md](docs/upgrade-4.md)._

**Upgrading: what breaks**

- `cts` is `cts.exe` alone (.NET Framework 4.8, which every PC with CODESYS has): no Python, no pip package. The installer puts `products\codesys-agent\dist` on the user PATH and offers to remove an old pip `cts` that would shadow it.
- The CODESYS menu has one entry, `cds-text-sync`: it starts the in-IDE agent and opens the quick window (Alt+Q). The `Project_*` scripts, the IronPython daemon and the pywebview windows are gone. `cts install` deletes nothing an older release left in ScriptDir: it names each old `Project_*.py` still listed under Tools > Scripting, which no longer works, for you to delete.
- A 3.x sync folder is not taken over: start in a new folder (`cts set-sync-folder` refuses one with `.dump/manifest.json`), then `cts export` the project into it.
- Git is required: the sync folder is a git repository (`cts set-sync-folder` sets one up), and the commands refuse a folder that is not one.
- A project finds its sync folder by an id (`cts-project-id` in Project Information) and this PC's `%LOCALAPPDATA%\cds-text-sync\projects.json`, not by a path stored in the `.project`; `cts status` names the folder `cts set-sync-folder` takes.
- The deny list is the `deny` array of the sync folder's `cds-text-sync.json`; the `cds-daemon-config` project property is no longer read.
- Analysis settings move from `cts-analyze.toml` to the `analyze` key of `cds-text-sync.json`, suppressions to `.cts-analyze/suppressions.json`; `--sarif FILE` replaces `--format sarif`. CTS0025 and CTS0045 are retired, and some findings get new fingerprints, so a baseline shows them stale once.
- The compare and merge programs are git's (`diff.tool`, `merge.tool`): `cts tool compare|merge NAME` and the `cts.compareTool`/`cts.mergeTool` keys are gone, and the Quick-window Settings page keeps only the program digit 7 opens.
- Commands gone or replaced: `cts ui`, `config ui`, `daemon start|stop`, `snapshot`, `last-result`, `text-status`, `app-state`, `update-pou`, `delete-pou`, `project-info`, `discover`, `engine`, `patch save`, `pou`, `rp`, `agent watch|bench|probe`; `read-vars` (`cts read` takes several names), `variable-map|snapshot|restore` (`cts snapshooter`), `install-menu` and `where` (`cts install`), `visu-lint` (`cts visu check`), `fsm ide|scan|show|ui` (`cts fsm`, `--disk`, `--mermaid`).
- Options gone or renamed: `docs --output` is `--out`; `import --whole|--no-refresh`, `sync|merge|project update --merge-tool`, `compare --tool desktop|difftool` and `verify --probe-timeout` are gone.
- The files on disk have no settings: `layout`, `view_root`, `profile` and `projections` are gone with the settings only the IronPython menu read (a `cds-text-sync.json` that still has them is read without them; the view is always `project-view/`, every textual object `.st`, every text list `.csv`). A text list's `.xml` no longer holds its rows: the first `cts export` or `cts sync` rewrites those files. `quick_key` is the one setting left, and `cts config` has no `--layer`.

**Sync: by objects, one `.st` per POU, git as the engine**

- `cts export` writes a POU or interface with its methods, properties and actions as one `.st` (`METHOD … END_METHOD`, `ACTION A_Reset:` … `END_ACTION`), and an `.xml` beside it only for what the `(* cds-text-sync: … *)` pragma cannot carry (it carries the build properties, POULevel, SpecialFunc, a task-local GVL's TaskForWrite and the like; `cts import` sets them, a removed one back to its default). A CFC, FBD, LD or SFC POU is an `.xml` with each member, ST ones too, an `Owner.Member.xml` beside it. `cts guide commands` and docs/scripts.md have the table of which object becomes which file. Two exports of unchanged content are byte-identical: no TimeStamps, sorted keys, no Library Manager placeholder resolutions.
- `cts compare`, `cts import`, `cts export` and new `cts sync` go object by object through the agent; nothing exports the whole project. The sync base `refs/cts/base` tells which side changed; `cts sync` carries both sides and merges edits that do not overlap, an overlap is a conflict (exit 2, `--take disk|ide`, for XML objects too). `--force` makes one side the other and keeps what it overwrote on `refs/cts/overwritten`. Text, XML objects (tasks, screens, devices, the Library Manager), text-list rows, new objects and folders, renames, moves into another folder (the object keeps its GUID) and deletes travel this way (an object deleted or renamed in the IDE leaves the disk too, and an `.xml` beside a `.st` follows the IDE's settings, written as `cts export` writes it or removed); `cts import --dry-run` shows the plan with its renames, moves and conflicts. A device's or folder's changed `.cds-object.xml` goes into the IDE like any XML object (a device of another type or version on disk is refused with the `cts project change-device` line that makes the IDE's one match), and a Library Manager that comes from disk loads the libraries it names (one that does not load is named). `sync --save` saves the project after a successful sync that changed it. The `cts guide commands` Files on disk section shows minimal `.st` templates and the sync refusal points there when a closing line is missing.
- `cts sync` labels each change `disk -> IDE` or `IDE -> disk`, and labels a merged change `merged`.
- A folder whose last object, a screen or another XML object, is deleted on disk goes from the IDE too, as one emptied by a deleted `.st` does.
- `cts compare` says the paths it lists are of files under `project-view/` in the sync folder; its JSON names that folder as `view`. An object changed in the IDE and on disk is marked `changed in the IDE too`, with the `cts import --dry-run` that tells whether the edits overlap.
- An object kept as XML that both sides changed is merged element by element: in `cts import`, `sync` and `export --tool`, and as git's merge driver for branches (`cts hook merge-driver`, set up by `cts set-sync-folder`), so two branches that each add a program call to one task keep both.
- An alarm group's `.csv` carries each alarm's message, a `Message` column and one per language, and `cts import` writes an edited message into the group's message list; that list no longer has a `.csv` of its own, and the other alarm columns stay the IDE's.
- A text list's rows are only in its `.csv`; its `.xml` keeps the rest, and `cts import` gives the IDE a changed or new `.xml` with the `.csv`'s rows, so a text list can be added or deleted from disk. Its languages can change in the `.xml` and the `.csv` at once: the rows go with the `.xml`. `visu from-svg` adds new captions to `GlobalTextList.csv` only. The `.csv` lists the rows by TextID, so a row the IDE adds does not reorder the file, and `cts import` matches rows by TextID whatever their order: a new row goes to the end of the IDE's list.
- New native `.xml` objects imported below a folder stay in that folder.
- Git's ignore rules (`.gitignore`, `.git/info/exclude`) leave view files out of export, import and compare: a colleague can leave the task configuration or the alarms to the owner.
- Speed: compare re-renders only the objects whose IDE TimeStamp moved (all of them once after a new cts build), git says which files differ from the base, an unchanged native object is not exported again, and `cts export` answers from git when no object changed since the base. A large project compares in seconds after its first run, and the agent runs that compare itself while nobody works (no input and no cts command for 15 s, after the project's objects changed), so a person's next compare, the quick window's header among them, finds the IDE side done.
- Git commands: `cts commit -m MSG [--tag NAME]` (sync, then commit; never a `*.project`), `cts branch`, `cts checkout TARGET [--disk-only]`, `cts log`, `cts merge BRANCH [--preview] [--take PATH=ours|theirs]`, `cts push`, `cts open` (the sync folder in your git program; branches are merged there, not in CODESYS). `cts status` names the branch, commit and uncommitted changes.
- `cts download` records the commit it put on the PLC; `cts plc-crc` and `cts log` name it. `cts download` and `cts connect` name the PLC they reached (`plc=`: the runtime's name, its address, or `simulation`). Uncommitted changes now suggest `cts commit` without suggesting stashing. After a commit or a full import Project Information carries `cts-source` (`main@1a2b3c4d · 2026-10-16 14:02`).
- `cts export` leaves a `.st` whose objects are the IDE's but for blank lines at a part's edges or the order of its methods, as `cts compare` calls it unchanged: a hand-written file no longer turns into a git diff on the first export.
- A sync folder remembers the project file its last export came from: with another copy open, compare says `base=other` and `cts sync` refuses.
- `cts compare` and `cts import --dry-run` mark an object deleted in the IDE (`ide_changed NAME FILE: deleted in the IDE`) and point to `cts sync` for it, not to `cts read-object`, which cannot find it; `cts read-object --body` reads a folder or the Visualization Manager too (its `.cds-object.xml`).

**Quick window (Alt+Q)**

- `1` Disk -> IDE and `2` IDE -> Disk merge an object both sides changed and open overlapping edits side by side in the merge program; Shift+1 / Shift+2 make one side the other (`--force`). `3` Compare (the disk, or the IDE against a branch), `4` Switch branch (a new branch on its first row), `5` Commit, `6` Commit and publish (the owner) or Pull and update (a colleague), `7` Open the sync folder in your git program, `8` Settings, `0` More: Format ST, the agent's activity, the line for an AI agent, the FSM map, the analysis findings.
- The header shows the branch, its last commit, `↑↓` against its upstream (fetched quietly) and what changed on each side; a row that cannot run now says why; a failure has a Copy link with the whole output.
- Settings: the sync folder, the program `7` opens, This PC (owner or colleague), the quick key (also `cts config set quick_key`), and Permissions, the deny list no cts command can change.
- With no project open it lists the known projects; a project without a sync folder on this PC opens on the sync folder row.

**Working as a team** ([docs/team.md](docs/team.md))

- The project file in the repository is its owner's: `cts commit --publish` commits it under Git LFS. A colleague's `cts project update` closes the project without saving, puts the published file back, pulls, imports the branch over it and saves.
- On a colleague's PC the project file is hidden from git (`skip-worktree`), a `pre-push` hook (`cts hook pre-push`) refuses a push to the default branch or of a `*.project` change with each reason on its own line, and the IDE's Library Manager and Project Settings stay off the disk.
- The role belongs to the PC (`projects.json`): `cts set-sync-folder --owner|--colleague`, or This PC in Settings.

**The in-IDE agent, the PLC and online commands**

- `cts read` suggests the closest declared names from the sync view when the PLC does not know a name (`did you mean: GVL.fbMotor1.tFbTimeout`).
- An empty `cts plc-log --cts` result says that ST code must log a `CTS|` marker to create records and points to `cts plc-log --tail N` for the raw log.

- The agent serves every IDE and PLC command, also while a dialog is open: a command a dialog blocks exits 3 with the ready `cts dialog answer` line, `cts dialog` reads it, and an unknown word after a command names its plain form and subcommands; a dialog that opened and closed while the command waited is named in the refusal. `cts connect` calls an application it creates on the PLC `app_created` in text and JSON.
- `cts connect [--ip]` logs in without changing what the PLC runs (`--ip` also gives the device the name that PLC reports, so a later login does not stop at "another device"; when no PLC answers it says whether this PC reaches the address at all); `cts download` downloads without dialogs and waits until the application is ready (`--ready-var`). New: `cts scan` (the gateway's Scan Network, with each PLC's IP), `cts reset --kind warm|cold|origin`, `cts boot-app`, `cts plc-log`, `cts project set-credentials|simulate|list-devices|device-types|change-device` (`change-device` is the IDE's Update Device: another device type or version; `list-devices` names what each device is and takes `--device`, which `device-status` had).
- `cts read` reads several names in one call, samples (`--samples`, `--interval`) and waits (`--until`); `cts write` writes several pairs in one PLC cycle and reads each back (`confirmed=`). Values are spelled by the IDE's own literal converter.
- New `cts plc info|ls|get|put|rm|mkdir|mv`: what the PLC runs (runtime, device, each application with its state and the project it came from) and its files, with the IDE offline: each command connects to the device for its run and leaves a login as it was; `cts plc-log` too no longer needs `cts connect`. `get` and `put` check the copy against the CRC32 the PLC computes for its file; `rm` removes a full directory only with `--recursive`. They replace `cts raw plc_files|plc_fetch|plc_upload`; `put`, `rm`, `mkdir` and `mv` answer to the deny list key `plc_upload` (denied by default).
- While the IDE is online every project edit is refused (`cts disconnect` first; the refusal names the command to repeat, `cts sync` or `cts commit` too); `cts status` says what works.
- With several IDEs open a command goes to the one whose project's sync folder holds the current folder; `--target` and `--expect-project` choose and check.
- Every command answers with a verdict line first (`ok|partial|error <command> key=value …`), then what to act on and `Next:`; `--json` is the payload, a failure's too (`message`, `next`).

**Tests and CI**

- `cts guide` names the ST unit test job and says a clean `cts compare` lets the deploy job skip `cts import`.
- New `cts test`: ST tests in a test application on a device in simulation, each logged through CmpLog, the log kept as a file; tests never reach a real PLC.
- `cts verify` (analyze, sketch lint, build, `--with-test`, `--deploy`) gives one status per stage on its line; `.test` plans run through the agent.
- `cts build` names the `.st` file, line and column of each message and lists the warnings; `--all-objects` also checks the objects no task calls; `--app NAME` makes another application of the project the active one and compiles it.

**Analysis, format, docs**

- `cts fsm` lists an object's transitions in source order, the order its `IF`/`ELSIF` branches are tested, and says its line numbers count from the implementation's first line; the state it starts in comes with where that is from (the declared value or the integer's default 0).
- `cts analyze` has 94 rules (new: CTS0100, an object no task, event or screen reaches), tuned on a large project for far fewer false findings. It analyzes only what CODESYS builds and reads the Library Manager, I/O mappings and screens; `--path` and `--changed` narrow the report, which ends with counts by rule. A project of 650 objects with 108 MB of screens takes seconds. The findings window (More, `5`) belongs to the agent. A run that exits non-zero (findings at `--fail-on`) says `error analyze`, as `cts verify` does.
- New `cts fmt [NAME] [--write]` for the IDE's code and `cts fmt --disk` for the files: indentation in editor columns, aligned declaration tables, spacing inside a statement left as written; More `1` shows each change side by side.
- New `cts new KIND NAME` writes a POU, GVL, DUT or member as a `.st` file for `cts import`.
- `cts fsm [NAME]` lists the state machines with their transitions and what looks wrong; the FSM window (More, `4`) draws them.
- `cts docs` writes `cts-docs/v4` for an AI agent: a card per object with its calls, callers, tasks and globals, a page per library.
- `cts guide` prints a map of a long guide (`--section`, `--all`); bare `cts guide` lists the common jobs as command sequences, and `cts guide --help` names the topics. An unknown command names the subcommand it matches (`cts list-devices` → `cts project list-devices`).

**HMI screens**

- The `cts visu` commands run in cts.exe: `from-svg` builds a screen from an SVG, `check` replaces `visu-lint`, and `types`, `describe`, `list`, `capture-frame`, `to-svg`, `preview` and the `.visu/` sketches (`new`, `lint`, `bind`) remain.
- `from-svg` fills a screen that is still empty and a project whose global text list is empty (CODESYS writes both lists self-closed). `--gvl NAME` adds to the project's GVL of that name in whatever folder it lies (a new one still goes to `POUs`); when several carry the name it writes nothing and asks for `--gvl-file`.
- A text field built by `from-svg` or `visu add` shows its value in the online visualization; it used to stay blank there, though the editor drew it.
- A plain `<rect>`, `<circle>` or `<ellipse>` is the IDE's rectangle with its bindings: `data-text` (centred, a format with `data-text-var`), `data-color-var` with `data-on-fill`/`data-on-stroke` (the colours while the BOOL is TRUE), `data-fill-var`/`data-stroke-var` (DWORD colours) and `data-cds-action`, so one shape is a rack cell that shows, colours and answers a click. `visu bind --text-var` and new `--color-var` bind shapes, `--gvl` declares their variables, `to-svg` writes them back.

**Install**

- `$env:CTS_BRANCH = "<branch>"` before the `irm … | iex` line installs a branch; `CTS_ARCHIVE` installs from a zip (`install.cmd` in a kit). An update keeps `projects.json`; a release up to 3.4.1 picked in the version menu is handed to its own installer.
- `cts install [--toolbar] [--all] [--check]` writes the menu entry, the agent and the toolbar button. Tested on CODESYS V3.5 SP22 (x64) and SP16 Patch 9 (x86). `cts --version` names the build commit.

**Development**

- The agent and cts.exe ship prebuilt in `products/codesys-agent/dist` (Git LFS), built by `tools/dist.py` in a commit of their own after the change.
- Dead code fails the checks (vulture, the agent build, `tools/DeadSymbols`).

---

### Version 3.4.0 (2026-10-07)

**PLC runtime log (`cts plc-log`):**
- With no options, `cts plc-log` prints the last 20 entries of the default logger and includes the logger list; `--loggers` lists them alone.
- `cts plc-log` reads the whole log: the runtime answers in batches, and the entries after the first batch (often after its "LOGGING BUFFER OVERFLOW" line) used to be missing, so the tail stopped at an old time.

- New `cts plc-log` reads the PLC runtime log (CmpLog) over the online device: no arguments lists the log files, `--file NAME` selects one, `--tail N` prints the last N lines, and `--output PATH` saves the whole file. With `--cts` it keeps only entries carrying the generated `CTS|<level>|<CODE>|<TAG>|k=v;k=v` marker and returns the well-formed ones as JSON records (`time`, `level`, `code`, `tag`, `fields`, `raw`) in `records`; `--level M|V` and `--code CODE` filter `records` and imply `--cts`. A marker line that does not parse is reported in a separate `malformed` list (`time`, `raw`, `parse_error`) with a `parse_errors` count that no filter changes, so bad lines can neither hide behind a filter nor be mistaken for events. Parsing runs on the CLI side (the IronPython daemon stays a plain reader); because the daemon returns only a tail, a plain `--cts` read saves the log into a temporary folder and reads the file there. `plc_log` also gets its own entry in the daemon timeout profile (minimum 60 s) for full-sized logs.

**Per-user settings and `cts config`:**

- Settings are now layered: code defaults, then a sparse per-user file, then the project's `cds-text-sync.json`. The per-user file is `%APPDATA%\cds-text-sync\defaults.json` on Windows and `$XDG_CONFIG_HOME/cds-text-sync/defaults.json` (or `~/.config/...`) elsewhere; it holds only the keys you changed, so a key added in a later version keeps its new default. Format keys (layout, view root, sync mode, profile, projections, view kinds) only seed a project that has no settings file yet; behavior keys (verbose logging, advanced debug, completion popup, pre-import backup, retention) are inherited at runtime unless the project file pins them. A view root in the per-user file is relative to each project's sync folder.
- The project settings file moves to schema version 2. A version-1 file (or one without a version) is migrated on the next save: a behavior value equal to the code default stops being pinned and starts inheriting, while a differing value stays pinned. Reading never rewrites the file.
- New offline `cts config` command. `cts config show` prints each effective setting with its source (`code`, `user` or `project`) and class (`format` or `behavior`), plus both files with their status and version; `--json` emits the same as a machine-readable object. `cts config set KEY VALUE` and `cts config unset KEY` change the per-user file by default, or the project file with `--project`; a project set of a behavior key pins it, an unset removes the pin. No daemon is required.
- The CODESYS project options dialog has two tabs. `General` edits the per-user file: its path, the format values new projects start with (view storage, custom view root, profile, text-first mode and the derived-view lists), the five behavior values, and `Reset to built-in`. Reset now empties the per-user file on the next save — including a projection or kind the dialog cannot show, and a key set with `cts config` — while an edit made after it is kept on top of the empty base. Cancelling still writes nothing. `Project` edits this project's file — the format controls as before, plus a behavior block that is either `Same as General`, greyed and following the General values live, or `Own for this project`, which pins all five in `cds-text-sync.json`. Saving writes the per-user file first and the project file only if that succeeds.
- The options dialog fits a small screen: 640×470, resizable, with both tabs laid out as two columns (format on the left, behavior on the right). The derived views are checked lists that show the profile's own defaults, so every option stays reachable. A field locked after the first export (view storage, custom root, text-first mode) explains why on hover, and so does a behavior control greyed by `Same as General`.
- The daemon settings no longer carry a second, differently formatted copy command. The Copy button has one form, `!cts --target ide-<pid> …`. A config that still stores the old `copy_command` key keeps working; the key is simply ignored.

**Operating guides ship with the CLI:**

- New `cts guide [TOPIC]` prints the operating guides (`workflow`, `commands`, `visu-svg`), and `cts guide <topic> --file <name>` reads a file shipped with a topic such as an example sketch. The guides are package data, so a pip/irm install now carries them and they always match the installed CLI version; `cts --help` points at `cts guide` as the first step. Unknown topics exit non-zero and list the valid ones. The `skills/` SKILL.md files are now thin wrappers that tell an agent to run `cts guide`, and the reference and example files they used to duplicate moved into the package.

**Working against a live PLC:**

- Project edits are refused while the IDE is online. `cts import` and the sync-folder and simulation-mode changes stop before they touch the project, the manifest or any file. The guard also catches a session the daemon did not open itself (Login pressed in the IDE after the daemon started), which used to let an import through and leave the new objects half-applied.
- `cts download` waits for the application to run (30 s budget, `--ready-timeout`; `--ready-var NAME` also requires that variable to change between two reads; `--no-wait` skips it). New `cts wait-ready [--var NAME] [--timeout N]` is the same wait for a Login or Download done by hand.
- Every daemon reply carries a `context` block (project, IDE id, cached PLC state, whether project edits are allowed, an optional hint) built from the cached view, so it costs no IDE call; text output ends with one `[ctx]` line. Response timestamps are ISO-8601 UTC with a trailing `Z`.
- The daemon is served from a WinForms timer instead of a loop inside the running script, so CODESYS no longer sits in "Executing script ... CANCEL" for the daemon's whole life: a download's progress paints and the PLC's stop/start is visible. A timeout leads with the verdict ("daemon busy with <method> for N s") and one action.
- New `cts snapshooter` drives the Snapshooter's tree/take/diff/restore from the command line; `restore` is a dry run unless `--apply`, and the command stays behind the daemon's deny list because `take --out` and `restore --apply` write a file and the PLC.

**Reliability and internal cleanup:**

- Checks for in-IDE agents from before this release are gone (an agent that exported the whole project for `read-object --body`, one that answered bare documents to `objects.export`, the `method_not_found` code no agent sends), as are the test-only `clear_registry_cache` and `DISPATCH_NAMES`; the dead-code check lists every exempt command handler by name instead of by pattern.
- The bridge's `start_agent` lost two parameters no caller passed; the agent folder comes from `CTS_AGENT_DIR` or the install, as the menu entries use it. A missing agent now points at `cts install-menu` or the installer, which bring the prebuilt DLLs, instead of a `dotnet build`.
- One rule picks the IDE for every command that talks to the agent directly (`dialog`, `branch`, `checkout`, `commit`, `compare`, `sync`, `import`, `read-object`, `snapshooter` and the rest): the second copy of it is gone, and `cts dialog` without an agent now names the launch command like the others.
- `cts project compare` works again: it calls the snapshot-compare handler, compares snapshot objects by identity instead of by XML attribute names, and `--against` is optional (the newest snapshot in `.dump` is used). The project-level `__VisualizationStyle` alias is listed under `project_alias_nodes` instead of being reported as missing from the export.
- Repeated exports of an unchanged project are byte-identical even across a CODESYS restart: a view file whose only difference is the object timestamp or the per-session `VisuStyleDefaultImages` temp path keeps its previous bytes.
- Failures are no longer silently turned into normal results: an unreadable file counts as dirty, a partial project walk or half-read project refuses the patch, unparseable XML is not diffed, and visu, online-state and project-info read errors are reported with their cause.
- A second persistent variable list is refused before CODESYS is asked to create it (the IDE dialog used to block the daemon). A reused text object is no longer reported as created, and a refused import says why.
- Unchecking a derived view on the Project tab now turns it off for real. The save used to write only the checked projections, and an unmentioned projection falls back to the profile's `default_enabled`, so the view stayed exported and came back checked. The tab now writes an explicit `enabled: false` for a box that was switched off, drops the entry again when a box goes back to the profile's own answer, and leaves a projection or view kind the profile does not offer exactly as the project file had it — so a save that changed nothing leaves the format part of `cds-text-sync.json` byte-identical.
- A custom view root inside the sync folder is stored in `cds-text-sync.json` as a relative path (`views/st`), so a clone on another machine resolves it to its own folder. It used to be written back as the absolute path of the machine that saved it. A root outside the sync folder or on another drive stays absolute.
- Daemon settings: the range labels under the poll slider are no longer cut off, and the Permissions tab's "checked = blocked" note, which sat below the page edge, is shown above the list.
- The daemon config fails closed: a config that cannot be read no longer drops the deny list.
- A result the CLI never received (for example after a timeout) is kept and can be fetched with `last-result`; it is written as UTF-8, so non-ASCII names survive under IronPython.
- Manifest paths are stored with `/` on every host and read with either separator.
- An object's view path now follows its parent's exported name instead of the casing CODESYS records in the object's own `Path` array. A device under `Plc Logic` whose children's `Path` said `PLC Logic` was exported twice — `PLC_Stabur/PLC Logic/…` next to `PLC_Stabur/Plc Logic/…` — on a case-sensitive filesystem, and the IDE then reported that it could not normalize the path casing. An existing split heals on the next export.
- `cts docs --output` no longer collides with the global option; the analyzer dependency pins a version that exists; both `cts` script declarations point at the same entry.
- Internals: one module each for the `.st` projection format, the daemon command wire envelope and the `cds-text-sync.json` loader; the command registry is the single source for daemon commands; engine modules load under one package name; the IronPython compatibility gate covers the whole host and flags Python 3-only imports.
- Internals: the ST comment/string blanker is now one implementation in `cts_shared`, shared by the analyzer and the sync engine instead of three byte-identical copies.

**Fixed:**

- The quick installer checks for `git` as it does for Python (winget, the download page, or skip), and the README lists Git among the requirements; the installer guide no longer says "No Git required". The README quick start goes through Alt+Q. Messages and guides that sent users to Tools > Scripting > cds-text-sync name the menu CODESYS shows: Tools > Scripting > Scripts > P. It ends with the three steps in CODESYS: Project_directory, Project_daemon, Alt+Q.
- The analyzer's string blanker kept one space for an escaped quote (`''`) though it consumed two characters, shortening the text by a byte and shifting every later offset. It now preserves the length, so offsets into a blanked `.st` stay exact.
- `cts import` no longer loses a disk change it could not apply. A modified object with no text form (a `Task.xml`, for example) used to appear in no result category, and the manifest refresh then overwrote the disk copy with the project's. The import now re-compares afterwards and, if something did not apply, returns `rc=2`, `partial=true` and the `unapplied_objects` list, and leaves the manifest and the disk copies alone.
- One daemon per CODESYS process. Every Execute Script run builds a fresh IronPython runtime, so a second run used to start a second daemon beside the first. The daemon state now lives in the AppDomain with a generation counter: a re-run asks whether to replace the running daemon, the old generation stops its own timer, and a named mutex on the pipe name refuses a second CODESYS process that would fight for the same pipe.
- Online commands (`cts read`, `cts write`, watches) no longer fail with `Stack empty`. The scripting engine keeps a private stack of script contexts that only a running script fills; the daemon now keeps its script's context and pushes it for the duration of an online command, and releases the watches it created after each command, so a stale expression cannot poison the next call.
- `cts read-log` no longer fails with `Value cannot be null. Parameter name: category`. The category is resolved from the IDE's own list (by GUID or description), defaults to Build, and an unknown one is answered with the list of valid categories; `--category` selects it.
- `cts write NAME text` on a STRING variable is accepted: when CODESYS answers `is not a literal`, the value is requoted as an ST string literal (`$` and `'` escaped), and the reply says so (`string_literal`, `note`, `written_as`); the read-back is confirmed against the quoted literal, not against the bare word that was typed. A number the PLC prints with its type (`INT#0`) now matches the `0` that was written, so such a write is no longer reported as not confirmed. A wrong value for a numeric variable still fails with its own error.
- A POU, method or action the agent creates is Structured Text whatever language an Add Object dialog last chose on that PC (a fresh profile starts on CFC), so `cts import` no longer stops at `POUObject Implementation has no text` on a new colleague's machine.
- A device no longer counts as changed in the IDE because a new session numbered its parameter elements (`PositionId`, `EditorPositionId`, added to elements the project file saved without them): `cts compare` and `cts import` leave such a device alone.
- A device's own placeholder resolutions (which library each placeholder resolved to, rebuilt from the libraries installed on the PC) are no longer compared, so a PC without the same fieldbus packages does not show the device as changed. The export writes them as none (`<Null>`), as the IDE does for a device that resolved nothing, so a device file no longer changes in git when another PC exports it; an import of that file gets them back from the IDE at once.
- `cts compare`, `cts import`, `cts sync` and `cts commit` refuse while git has view files it could not merge, naming them; before, `cts sync` after a `git pull` that stopped at a conflict wrote the file with git's conflict markers into the IDE as the object's code.
- `cts export` keeps the indentation of a body's first line (it was cut, and `cts sync` right after an export wrote the body back as a change), and `cts sync`/`cts commit` write an IDE text in the export's form (no blank edge lines), so a file reads the same whichever command wrote it. The next export puts the lost indentation back in such files.
- On a PC that is not the project's owner, a Library Manager that differs in the IDE (a CODESYS installation without the same libraries, say) is no longer written to disk or committed by `cts sync`/`cts commit`, and `cts compare` counts it as unchanged; cts prints that only the owner changes the project's libraries.
- A save that fails after an import (`cts checkout`, `cts project update`; a dialog up in the IDE, say) is named on the output with what to run next, where the line only said `saved=false`; when a dialog is up in the IDE (CODESYS asks about the compiler version as a project from an older version loads), the output names it: the save finishes once it is answered.
- `cts verify --only build` asks the in-IDE agent whether the IDE answers, where it asked the daemon and skipped the build when no daemon ran; only the test stage still needs the daemon.
- The first check of an IDE session writes an IDE edit to disk even when it brings back a text the object had earlier: the IDE counts as behind the disk only when the object last changed in the IDE before the sync base took the file's current version, where a repeated edit was taken for a project closed without saving and left out.
- An action added in the IDE to a POU the disk already holds is no longer missed: `compare`, `sync` and the first check of an IDE session write it into the POU's file, and `import --force` deletes it (after keeping it on `refs/cts/overwritten`). Its kind came only from a parent new in the IDE as well.
- A project with a visualization no longer shows its visualization style (`__VisualizationStyle`) as changed in the IDE each time it is opened again: the style's default images, which CODESYS numbers anew in every session, compare by their content.
- The script overview (`docs/scripts.md`) describes the sync folder as it works since a project finds it by its id: it no longer says the path is stored in the project or that a relative path serves every machine, and it names the owner.
- `--target ide-<pid>` (and `CTS_TARGET`) chooses the IDE for `compare`, `import`, `export`, `sync`, `commit`, `checkout`, `branch` and the other commands that read the IDE's tree, and `--expect-project` is checked for them: with several IDEs open these went to the one whose sync folder holds the current folder or refused, and the refusal named a `--pid` option those commands do not have. `cts agent --help` no longer calls the agent experimental.
- `--json` output stays pure: the `[INFO] Timeout: ...` line is printed only in text mode and always to stderr, so stdout carries the payload and nothing else.
- The scripting-API check (`tools/check_script_api.py`, now part of `ci_product_checks.py`) compares every scripting call the bridge makes with a snapshot of the API generated from the CODESYS assemblies. It found `projects.close`, which does not exist; `cts project close` now reports that instead of raising `AttributeError`.

---

### Version 3.3.0 (2026-09-30)

**Multi-instance IDE support & Protocol v2:**

- **Targeted routing (`--target ide-<pid>` / `CTS_TARGET`):** Work with several CODESYS IDE instances and projects simultaneously behind a single `cts` CLI client. When multiple IDEs are running, `cts` resolves and addresses commands directly to the targeted process.
- **Protocol v2 handshake:** The reverse named pipe now uses a multi-instance handshake (`hello`, target selection, `release`). When no target is passed and multiple live daemons are discovered, `cts` refuses with an `ambiguous_target` error and prints ready-to-run `--target` commands.
- **Target errors & project guards:** Clean error reporting for `ambiguous_target`, `unknown_target`, and `no_project`. The `--expect-project NAME|PATH` option guards write operations from modifying the wrong project if switched in the IDE.
- **Instance metadata in results:** Every command output (JSON and text format) now carries the instance identity (`ide-<pid>`) and current active project name/path in metadata and footer lines.
- **Help discovery header:** `cts --help` now probes for live daemon instances and displays target status and project info right in the help banner.
- **Daemon UI target line & Copy button:** The daemon window displays a docked target panel (`IDE: ide-<pid> · <project>`) with a `Copy` button that generates `!cts --target ide-<pid> [--expect-project <name>] --help` for immediate pasting into agent sessions.

**Library projects:**

- **`cts build` on a `.library`:** a library has no application, so `build` used to stop with "No active application found to build". It now runs the library check (`check_all_pool_objects`) and reports errors and warnings in the usual build format.
- **`cts build --install`:** does what the IDE button "Save project and install into library repository" does. After a clean check it saves the project, writes the compiled library and installs it into the System repository, replacing an installed copy of the same version. Nothing is installed if the check reports errors, and the CLI prints the reason when the installation itself fails.

**Other changes:**

- Setting a project's sync folder is now one dialog with the answer already in it: a folder named after the project (`<project>-cts`) beside the `.project` file, stored as a relative path so a clone on another machine needs no reconfiguration. It replaces the two-step "browse or type" flow — the suggestion has to live in a text field, because a folder browser silently ignores a preselected folder that does not exist yet. Browsing to a folder inside the project is stored relative too; a path typed by hand is kept exactly as typed.
- Commands no longer dead-end on an unconfigured project. Any of them that needs a sync folder and finds none offers the setup dialog and then carries on with the answer, so the alphabetical script menu can be entered anywhere rather than only at `Project_directory`. Lookups that must not interrupt — the daemon, and diff files written mid-compare — stay silent as before.
- The first time a folder is configured, `Project_directory.py` continues into the options dialog. That is the only moment when the sync mode is still free: the manifest fixes it on first export. Cancelling there keeps the folder and the defaults.
- New project option **Advanced debug: also log IDE script messages**. With it on, everything an IDE action (import, export, compare) prints to the CODESYS Messages window is copied into `.dump/sync_debug.log` as `[script]` lines, together with the traceback of any unhandled exception. A failure after the engine step, such as a failed pre-import backup or patch apply, used to leave the log ending at "Applying changes from …" with the cause only in the Messages window. The option implies "Save detailed engine logs in .dump".
- Export no longer warns "Could not read existing manifest" on a Windows machine whose default encoding is cp1252 when object names contain non-ASCII text. The manifest is written as UTF-8, but one reader opened it with the platform default, failed to decode it, and export then carried on as if there were no previous manifest.
- The release archive no longer carries the documentation's demo GIFs. `git archive` builds the release asset, so `img/` was shipping 8.3 MB into every user's program folder — 64% of a 12.8 MB install that nothing at runtime reads. An install is now 4.6 MB unpacked (1.4 MB downloaded). The GIFs stay in the repository, so the docs render unchanged on GitHub; a copy of `readMe.md` opened locally from the install folder shows broken image placeholders instead.

---

[Older releases](docs/changelog-archive.md) — newest first.
