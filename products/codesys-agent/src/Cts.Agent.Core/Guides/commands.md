# `cts` Command Selection

Use this reference as a routing guide. Confirm exact syntax with the installed `cts --help` and `cts <command> --help`.

Every command answers with **one verdict line first**: `<ok|partial|error> <command> key=value ...`, carrying only what decides the next step (`ok compare unchanged=26 modified=0 not_importable=0`, `error build errors=2`). Below it is what to act on, then the line naming the IDE and the project the command ran against (`ide-3444 · cts-reference-project`); a failure names the cause and, when cts knows the way out, ends with `Next: <command>`. `--json` (same as `--output json`) prints the full machine payload and nothing else — the form to parse; a failure prints one object too, with `ok: false`, the `command`, the `error` the verdict line names, the reason as `message`, the `next` command when there is one and the data it carried (a failed build's `messages`). `--pretty`/`-p` (`--output text`) prints the human-readable dump. All three, `--target` and `--expect-project` work before or after commands that do not define their own `--output`. With two or three IDEs open, a command without `--target` goes to the IDE whose project's sync folder holds the current folder (or the command's `--sync-folder`), so run cts inside the project's folder; when no IDE's sync folder holds it, cts refuses and lists `cts --target ide-<pid>` for each with its sync folder, and when two hold it (a copy of the project open in a second IDE) it lists them with their project files. `CTS_TARGET=ide-<pid>` sets the target for every command of a shell. For example, both `cts --json ping` and `cts ping --json` work; `cts test --output PATH` still names the log file.

## IDE commands

A command that talks to CODESYS goes to the in-IDE agent. When no agent answers, start the IDE with `cts project open --path <p> --launch`, or run `cds-text-sync` once from the CODESYS menu (Tools > Scripting > Scripts > C > cds-text-sync).

## Timeouts and failures

Each command waits as long as its kind needs (the agent's timeout profile);
`--timeout SECONDS` overrides it. Export, compare and import go object by
object and take seconds even on a large project; a build, a connect or a
download can take minutes.

A timeout stops the CLI waiting; it does not cancel the IDE operation. Check
`cts status` and `cts compare` before retrying a timed-out import. Common
failures and their next steps:

| Failure | What to do |
|---|---|
| `dialog_opened` (exit 3) | Answer with the printed `cts dialog answer …`, then inspect `cts status` (a build's outcome is its `last_command`); the command is still running. |
| `IDE error: Timeout...` | Allow more time for the project-sized operation; the IDE may still be working. |
| `Not connected...` | Run `cts connect`. |
| `Forbidden by the deny list` | The project's deny list refuses it; see `cts permissions`. |
| `Invalid expression` | Check that the variable path is exported to the online application. |

## Guides

| Goal | Command |
|---|---|
| List the shipped operating guides | `cts guide` |
| Read the operating rules | `cts guide workflow` |
| Read one section of a long guide (a long guide prints its opening and the map of its sections) | `cts guide visu-svg --section "Layout rules"`; `--all` for the whole |
| Read a file shipped with a topic | `cts guide visu-svg --file examples/pid-schematic.svg` |

## IDE and State

| Goal | Command |
|---|---|
| Check that the in-IDE agent answers, even while a dialog is open | `cts ping` |
| Inspect the IDE, project, sync folder, and PLC state, and the commit the IDE's code came from | `cts status` |
| Configure the project sync folder (and make it a git repository root) | `cts set-sync-folder [PATH] [--owner\|--colleague] [--save]` |
| Read CODESYS IDE messages | `cts read-log` |
| Inspect the project's command permissions | `cts permissions` |
| Read back the outcome of a build you interrupted | `cts status` (`last_command`), `cts read-log` (its messages) |

The permissions (the deny list) are the `deny` array of the sync folder's `cds-text-sync.json`, tracked in the project's repository: every clone has them, a change shows in git and takes effect on the next command. Without the key (or without a sync folder) the built-in list applies (`reset_plc`, `create_boot_app`, `plc_upload`); a list replaces it whole, so `"deny": []` allows everything. A file cts cannot read refuses every gated command. The agent enforces them; `cts permissions` reports them. No cts command changes them: a person does, in the IDE (the quick window, Settings, Permissions: each key with what it stands for, blocked or allowed, switched by Enter), or by editing the file; so an agent a key refuses cannot lift it.

The agent is not a background service: it runs **inside** CODESYS. `cds-text-sync` (Tools > Scripting > Scripts > C > cds-text-sync) starts the agent, which every command needs, and says how to reach it (Alt+Q, or `cts` in a terminal); nothing starts it without the user. `cts install` writes the menu entry *and* deploys the in-IDE agent next to it (CODESYS closed; `--check` only says what is out of date). `cts project open --path <project> --launch` starts the IDE on that project with the `cds-text-sync` stub as its startup script, then has that IDE's agent open the project (`agent=ide-<pid>`) — nothing to click; a dialog the load raises (a project saved by a newer CODESYS, a compiler version that is not installed) ends the wait with exit 3 and its `cts dialog answer` line, and the load goes on once it is answered (`cts status` shows the project); the agent's message goes to the IDE message list instead of a box. An IDE whose agent already has the project open is used instead (`launched=false already_open=true`). Without `--launch`, a saved, offline project open in that IDE gives way to the new one (`closed=<name>`), as File > Open does. `cts project new --path <file>` needs no IDE: it writes an empty project (`.project`) or an empty library (`.library`) from the installation's `Templates\Empty.project`, as CODESYS' New Project does, and `cts project open` then opens it; `cts lib add` gives it a Library Manager with its first reference, and a library to install needs Company, Title and Version in its Project Information. `cts project close` closes the project (`--save` saves it first, `--discard` drops unsaved changes); with `--quit` CODESYS exits too, as File > Exit does, and cts waits for the process to end (`quit=true`). The IDE is the newest CODESYS installed under Program Files unless `--codesys <exe>` names one; that installation's profile is passed when it ships exactly one, so a machine with several versions does not stop at the profile dialog; else `--profile "<name>"` picks it.

The agent logs to `%TEMP%\cts-agent.log`. `cts status` is answered by the agent: it reports the project and the PLC from the IDE. When a command gets no answer, the CLI says which case it is — the IDE is busy, or it is blocked by a modal dialog (that last one is refused at once, with the dialog's options, buttons and id, instead of waiting out the timeout). A blocked IDE is answerable from the CLI: `cts dialog` reads what is on screen and `cts dialog answer` chooses the options and presses a button — `cts guide dialog`.

## Folder and IDE Synchronization

| Goal | Command |
|---|---|
| Refresh projected files from the IDE | `cts export` |
| Compare the IDE with projected files | `cts compare` |
| Compare including the unchanged objects | `cts compare --all` |
| Compare file by file in GitHub Desktop or a diff tool | `cts compare --tool` |
| Compare the IDE with a branch, tag or commit | `cts compare --tool --against REF` |
| Show the compare and merge programs, and choose the one `cts open` starts | `cts tool`, `cts tool open NAME` |
| Preview folder-to-IDE changes | `cts import --dry-run` |
| Apply folder-to-IDE changes | `cts import` |
| Apply and save the project | `cts import --save` |
| Compile the active application | `cts build` |
| Compile another application of the project | `cts build --app NAME` |
| List the branches, or create one and switch to it | `cts branch [NAME]` |
| Switch to a branch or tag and carry it into the IDE | `cts checkout TARGET` |
| Switch the sync folder only, the IDE as it is | `cts checkout TARGET --disk-only` |
| Commit the sync folder's files (optionally tagged) | `cts commit -m MSG [--tag NAME]` |
| Publish the project file with the commit (owner) | `cts commit -m MSG --publish` |
| Send the branch to the team's repository | `cts push` |
| Pull and carry the branch into the IDE (a colleague: onto the published project file) | `cts project update` |
| The check git's pre-push hook runs (installed by `set-sync-folder`) | `cts hook pre-push REMOTE [URL]` |
| The merge git runs for a view `.xml` (installed by `set-sync-folder`) | `cts hook merge-driver BASE OURS THEIRS [PATH]` |
| List the commits to go back to, and which one a PLC got | `cts log [-n N] [--all]` |

### Export and sync base

`cts export` **is** the export-text command — there is no separate `export-text` (or "export text") command to look for, and `cts import` is its reverse.

In such a repository, every `cts export` and `cts import` also move `refs/cts/base` (a ref, not a branch): the view as it was when disk and IDE last agreed. Export records the whole view, except files changed on disk since the last sync (they keep their old base) and unmanaged files; import carries only the files of the objects it wrote, created, renamed or deleted. The JSON answer of `cts export` names the new commit in `base` (or `unchanged`). It is what tells, for an object that differs later, which side moved, and which files `cts import` carries and `cts export` keeps as pending: a file the base holds counts as changed on disk exactly when it differs from the base in the normal form. The line of `cts export` counts the files it kept (`kept=N`), one line each. `cts export --tool` then merges each object in them the IDE changed too, and one whose edits overlap opens side by side in the merge program for the person, the IDE's text on the right; what is saved there goes to the IDE and the file (`merged=N`), one closed without saving stays kept. `cts export --force` makes the disk the IDE: it writes over those files and removes every object file it does not write, after the view as it was went on `refs/cts/overwritten`. No repository: `cts import` is refused with the reason (`cts set-sync-folder` makes one, then `cts export`).

The base belongs to the project file whose export or import recorded it (`.git/cts/base-project`). With another file of the project open (an older version, a colleague's copy, the file of another branch), there is no common base: `cts compare` says `base=other` and counts every difference as a plain one, `cts sync` refuses, `cts export` writes the open project over every file without an uncommitted change (a file that differs from the commit stays, as pending), and `cts import` gives the IDE the disk's text; either one records the base for the open project.

A folder a cds-text-sync 3.x export wrote (`.dump/manifest.json`) is not taken over: `cts set-sync-folder` refuses it. Choose a new folder and `cts export` the project into it.

cts remembers the commit it left on `refs/cts/base` (in `.git/cts`). When the ref names another one, something other than cts moved it, and `cts compare`, `cts import`, `cts sync`, `cts export` and `cts checkout` refuse with both commits: `git update-ref refs/cts/base <cts's commit>` puts it back; `git update-ref -d refs/cts/base` drops it, and the next `cts export` starts a new one.

### Files on disk

| Object | Files in `project-view/` |
|---|---|
| ST program, function block, function, interface, with its methods, properties and actions | `Name.st`, the members inside |
| GVL, persistent variables, task-local GVL, DUT | `Name.st` |
| Network variable list (sender) | `Name.st` and `Name.xml`, its network settings |
| Network variable list (receiver) | `Name.xml`; the IDE writes its variables from the sender |
| CFC, FBD, LD or SFC POU | `Name.xml`, each member `Name.Member.xml` beside it, ST ones too |
| Graphical method or action of an ST POU | `Owner.Member.xml` beside `Owner.st` |
| Text list, global text list | `Name.csv`, its rows, and `Name.xml`, the rest of the list (its languages) without the rows |
| Alarm group | `Name.csv`, its alarms with their messages (only the `Message` columns go back to the IDE), and an `.xml` for the group and one for its message list |
| Folder | a directory with `.cds-object.xml`; an empty one `Name.xml` |
| Anything else: visualization, task, device, Library Manager, project settings | `Name.xml` |

An `.st` or `.csv` is edited as text; an `.xml` goes back whole and is merged element by element.

Minimal Structured Text files use the same closing lines as export. Replace the example names and add declarations or statements as needed:

```st
PROGRAM PRG_Example
VAR
END_VAR
// --- implementation ---
END_PROGRAM
```

```st
FUNCTION_BLOCK FB_Example
VAR
END_VAR
// --- implementation ---
END_FUNCTION_BLOCK

METHOD M_Example : BOOL
// --- implementation ---
END_METHOD
```

```st
FUNCTION F_Example : BOOL
VAR
END_VAR
// --- implementation ---
END_FUNCTION
```

```st
VAR_GLOBAL
END_VAR
```

```st
TYPE ST_Example :
STRUCT
END_STRUCT
END_TYPE
```

`cts new pou NAME --kind program|function|function-block`, `cts new gvl NAME`, and `cts new dut NAME --kind struct` create these objects for you; `cts new method POU.METHOD` adds a method.

An `.st` may start with one cts pragma line, `(* cds-text-sync: TypeGuid="{...}" External CompilerDefines="SIM" *)`: `TypeGuid` pins a type the text does not tell (persistent or task-local variables), and the other words carry the object's settings the text cannot, when not the IDE's default: the build properties `ExcludeFromBuild`, `LinkAlways`, `External`, `EnableSystemCall` (each its bare name when on), `CompilerDefines` and `MemoryReserveForOnlineChange`, and `POULevel`, `SpecialFunc`, `AddAttributeSubsequent`, `ParameterList` and `TaskForWrite` (a task-local GVL's writing task, by its id). `cts import` strips the line from the text and sets each setting the IDE does not have yet through the agent; one the line no longer names goes back to its default. A setting the line cannot hold (a value with a quote), or one cts does not know, keeps an `.xml` beside the `.st` with them.

### Compare

`cts compare --sync-folder PATH` compares that folder with the IDE; `cts sync`, `cts import` and `cts export` with `--sync-folder PATH` refuse unless the open project's sync folder is that one.

`cts compare` answers "what differs", nothing else: the counts and one record per changed object (name, view file, and for a text object the parts that differ). It is a few hundred bytes for a clean project; `--all` adds the unchanged objects. It goes by objects, like `cts import`: each object of the view (the `.st` objects, the `.xml` and text-list `.csv` files) is found by its path in the IDE tree and compared with what the IDE holds, read by the in-IDE agent (`objects.texts`, `objects.export`, `objects.fields`). A native object found equal to its `.xml` is not exported again by the next compare, sync or import while neither its file nor its IDE TimeStamp moved (`.git/cts/same-natives.json`). The sync base (`refs/cts/base`) says which side moved: `modified` changed on disk (`cts import` writes it; `ide_changed: true` on the record when the IDE changed it too), `ide_changed` changed, new or deleted only in the IDE (`cts sync` writes it to disk, and for a deleted one removes its `.xml` and `.csv`, or takes it out of its `.st`; an object with no text form new in the IDE, a visualization say, is named with the `.xml` the export would write for it), `added` new on disk and `deleted` removed from disk since the base (`cts import` creates or deletes it). On a PC that is not the project's owner, a Library Manager or the Project Settings changed only in the IDE count as unchanged, with a line saying so: only the owner changes the project's libraries and settings (another CODESYS drops or adds its own system libraries, and "Set All to Newest" writes its compiler version into the Project Settings). A view file Git's ignore rules match (`.gitignore`, `.git/info/exclude`, the global excludes file), a tracked one too, is no difference: `cts compare`, `cts import`, `cts sync` and `cts export` leave it as it is and a line counts them, another names the ones the IDE holds otherwise than the disk (an edit on disk never reaches the IDE by itself: `cts import --include-ignored PATH` carries one file like any other); a colleague lists there what only the owner changes (`**/Task Configuration/`: a folder object is `<folder>/.cds-object.xml`), and a rule over the application, or over a folder but not what is below it, is refused before anything is written. A line names folders of the view git tracks in two spellings that differ only in case (Windows holds them as one folder, and a copy of the sync folder merges them): keep the spelling `cts export` writes and `git rm -r --cached` the other. Without a base every difference is `modified` and an object only the IDE has is `ide_changed`; the line starts `base=none` and its first detail says `cts export` starts one. What `cts import` would refuse is listed under `not_importable` with the reason, never as "unchanged". `last_edit` (`ide_edit=`/`disk_edit=` in the line) says when each side last changed what differs, in local time: the newest IDE TimeStamp of the objects the IDE changed, the newest modification time of the files changed on disk; a hint for which edit is the later one, the base still decides which side moved. The sync folder must be a git repository.

### Compare tools

`cts compare --tool` shows the difference file by file, for a person: it records the IDE's state on `refs/cts/ide` (a ref, not a branch: git tools do not list it and a plain push leaves it behind; the commits are authored `cts`, and an IDE whose objects match the last one in the normal form makes none) and opens it against the view files on disk. By default that is GitHub Desktop when it is installed: cts keeps a repository for it in `.git/cts/desktop/<folder> (IDE vs disk)` whose branch `ide` is the snapshot and whose files are a copy of the view on disk, so Desktop's Changes are the disk against the IDE (red is the IDE, green the disk). It is a copy, brought up to date by each `cts compare --tool`: nothing done there reaches the sync folder; Desktop adds it to its list the first time. With a difftool, cts starts `git difftool --dir-diff` between the snapshot (left) and the view files (right), and an edit made in the tool is written to the file. The program is git's: its `diff.tool` (`winmerge`, `kdiff3` or a git difftool with `difftool.NAME.cmd`), else GitHub Desktop when installed, else WinMerge; with none of them the command fails and says so. Files new on disk show as added either way (through a separate index in `.git/cts`; yours is not touched). cts does not wait for the tool: the line is `ok compare tool=<github-desktop|tool> files=<N> ide=<commit>`, and with no file differing (`files=0 unchanged`) nothing opens. It compares text, not objects: a file the export would write the same way shows no difference. `--against REF` puts a branch, tag or commit in the disk's place: the IDE against the view files that branch holds, both sides out of git (the disk's own edits are not part of it); Desktop gets its own copy, `.git/cts/desktop/<folder> (IDE vs <ref>)` (a `/` in the name becomes `-`), whose Changes are the branch against the IDE, a difftool gets the snapshot left and the branch right. The line adds `against=<ref>`; a name git does not know fails the command, and `--against` without `--tool` is refused.

`cts tool` names the programs a person sees, each with the ones found installed: the compare (`cts compare --tool`, above), the merge, which shows edits both sides made to the same lines side by side (`cts import --tool`, `cts export --tool`): git's `merge.tool` when it names `kdiff3`, `winmerge` or `vscode`, else the first of those installed, and the open program (`ok tool compare=<program> merge=<program> open=<program> chosen=<open|none>`). Compare and merge are chosen in git (`git config --global diff.tool NAME`, `merge.tool NAME`). `cts open` starts a person's git program on the sync folder, where branches are merged and the history read; `cts tool open NAME` chooses it (desktop, vscode, zed, explorer or a program's full path, which gets the folder as its argument; `cts.openTool` in the user's git configuration), `auto` drops the choice; unchosen it is the first of GitHub Desktop, VS Code and Zed installed, else Explorer (`ok open folder=<path> in=<program>`). A program that is not installed, or a name cts cannot open, is refused with nothing stored.

### Branches and commits

The IDE project is a working copy of the sync folder's branch. `cts branch` lists the branches and the tags (`tags=N`, names in `--json`); `cts branch NAME` creates a branch at the current commit and checks it out: nothing changes in the files or the IDE. `cts checkout TARGET` switches to a branch, a tag or a commit (detached) and makes the IDE match it: git checks the target out, the import carries every object the switch changed (new, changed, deleted, renamed) and the project is saved (a switch that changes no object, such as back to a branch at the same commit, saves nothing); the line is the import's, after `branch=` and `commit=`. It starts only from a synced state and refuses, with nothing changed, while the IDE is online, without a sync base (`cts export` first), with uncommitted changes in the sync folder (commit them first; the open project's own file does not count, every save changes it), or when `cts compare` finds any difference (`cts sync`, `cts import` or `cts export` first). When the import would refuse a change of the target, git goes back to where it was. `--sync-folder PATH` refuses unless the open project's sync folder is that one. `cts checkout TARGET --disk-only` switches the sync folder and nothing else: no IDE is needed, none of the checks above apply (git itself refuses a switch that would overwrite an uncommitted change), and the sync base stays, so `cts compare` then shows what the target changes against the IDE and `cts import` carries it; the line is `ok checkout branch=… commit=… disk_only=true`. It works on the folder given with `--sync-folder`, else the one around the current folder.

`cts commit -m MSG` records the sync folder on the checked-out branch as it is on disk: `git add -A` and `git commit`, so every change git does not ignore is committed, except a `*.project`. The IDE is not written: its edits reach the commit only after `cts export` or `cts sync`. The line is `ok commit branch=… commit=… files=N`; `files=0` when there was nothing to commit. When `cts compare` finds the IDE and the disk differ, the commit still goes, with `ide_differs=N` on the line and a `[WARN]` line. `--tag NAME` adds an annotated tag on the result, a target for `cts checkout`. A detached HEAD (`cts branch NAME` first) or an existing tag is refused. The user's git identity is used, cts' own when git has none.

After `cts commit` (not `--publish`, whose file is saved before its commit) and after an import or sync that carried every difference, the project's Project Information gets `cts-source`: `<branch>@<commit>`, `+uncommitted` when the view held changes no commit has, and when (`main@1a2b3c4d · 2026-10-16 14:02`). It is written only when the label changes, so a run that carried nothing leaves the project unmodified, and the view leaves it out of `Project Information.xml`: it is never a change to commit. A project file opened anywhere says where its code came from (`cts status` shows `source`, CODESYS shows it under Project Information); edits since then are what `cts compare` finds.

`cts log` lists the latest commits of the checked-out branch (`-n`, default 20; `--all` every branch and tag), newest first, one line each: short id, date, subject, then `HEAD`, the branches and `tag: NAME` at it and `downloaded` when a `cts download` put that commit on a PLC (`cts plc-crc` names the one the PLC runs now). The line is `ok log branch=… commit=… commits=N`; `--json` carries the full ids. Any of them is a target for `cts checkout`.

### Team: publish and update

The project file in the repository is the base the team opens before `cts import`; only the project's owner puts it there. `cts commit --publish` does the commit, then saves the project and commits its file under Git LFS (`published=PATH` on the line): the `*.project` the repository tracks, else the open file when it lies in the repository, else `<name>.project` at the root, copied from wherever the open one is. The owner is the machine that gave the project its id, or one named with `cts set-sync-folder --owner` (kept in the machine's `projects.json`, never in the repository; `--colleague` makes a machine a colleague's again, and the quick window's Settings, This PC, switches the two); on another machine `--publish` is refused, as it is without Git LFS. A plain `cts commit` never commits a `*.project`, so the IDE saving a colleague's copy never replaces the base. Those saves still change the tracked file. On a colleague's machine `cts set-sync-folder` hides them from git (`git update-index --skip-worktree` on each tracked `*.project`, `skipped=N` in the JSON; the owner's machine clears it), so `git status` and a git program never offer the file; `git pull` still stops at a saved copy when the owner published a new one, and `cts project update` is the pull. `set-sync-folder` also installs git's pre-push hook (`.git/hooks/pre-push`, `hook=installed|current|kept` on the line; a hook of the user's own is kept and named, the one `git lfs install` writes is replaced, as cts' hook runs `git lfs pre-push` itself). The hook runs `cts hook pre-push`, which asks the machine's role at each push: on a colleague's machine a push to the remote's default branch (its `HEAD`, else `main` and `master`) or of a commit no remote has yet that changes a `*.project` (the owner's publishes it fetched do not count) is refused, exit 1, nothing pushed; the owner's machine and a folder of a project with no id pass. It is a guard on this PC against a slip (`git push --no-verify` passes it); the team's server protecting the branch is the rule. It closes the project without saving, puts the committed project file back (copied to the open one when that lies elsewhere), runs `git pull` (a merge, when the branch has an upstream), points the sync base at the commit that published the file, opens it and imports the branch's code over it, then saves: `ok project-update published=… branch=… commit=… pulled=true|false` and the import's counts. The colleague's own saves are not kept: what they made is in the branch, and their CODESYS may hold other libraries or another version. On the owner's machine the IDE has the published project already: `cts project update` there runs `git pull` and imports what came, with the sync base where the last sync left it, then saves (no `published=` on the line); a branch without an upstream, or a pull git stops, is refused with nothing imported. It refuses, with nothing changed, while the IDE is online, on a colleague's machine without a published project file or Git LFS, and when the IDE changed an object since the last sync (`cts sync`, then `cts commit` takes it into the branch); without a sync base (a fresh clone) the IDE is not asked. A pull git stops (an uncommitted edit in its way, a conflict) is named on the line and the branch is imported as it was; a conflict left in the files makes the import refuse with their names. On a colleague's machine the IDE's Library Manager and Project Settings never go to disk (see `cts compare`).

`cts set-sync-folder` also gives this PC's git a merge for the view's `.xml` files (`git config merge.cts`, `*.xml merge=cts` in `.git/info/attributes`, which git reads before the repository's `.gitattributes`): `cts hook merge-driver` merges an object element by element, so two branches that each added a program call to a task, or a library to a Library Manager, keep both, in order, and one side's changed settings join the other's. A list's items are told apart by name (a program call's name, a library's placeholder or namespace, a dictionary entry's key); a list whose items have none, and one value both sides changed, or an item one side removed and the other changed, stay a conflict of the whole file, left as this branch had it: take a side in your git program. Every merge of this PC's git uses it: `cts project update`'s pull and your git program's; a PC without it keeps the repository's rule (`*.xml -merge`: the whole file is a conflict when both sides changed it).

`cts project update` pulls the branch's upstream (`git pull`, a merge) and imports what came. When the team changed the same lines as this PC, git stops with the files it could not merge and the update refuses naming them, nothing imported: resolve them in your git program (`cts open`), commit the merge, then run `cts project update` again, which imports it. While a merge is unfinished the update refuses before anything else.

`cts push` is `git push` of the branch checked out: to its upstream, else, the first time, to the repository's only remote, which becomes its upstream (`git push -u`); several remotes and no upstream is refused with the command that names one. When the repository keeps a file under Git LFS (the published project file), `git lfs push` goes first, so the remote never gets a pointer without its file. Only commits go (`cts commit` first). The line is `ok push branch=… to=<remote>/<branch> commits=N`, N the commits the remote lacked. A remote with commits the branch lacks is refused (pull them first: `cts project update`). git asks for no password on a terminal: its credential helper answers, or the push fails with git's words.

### Project setup and editing

The agent ships with cts: an IDE still running an older one, missing a method a command needs, is refused with one line saying to update it (`cts install`) and restart CODESYS — no command routes around it.

A project finds its sync folder by its id, not by a path. `cts set-sync-folder` gives the open project an id (`cts-project-id` in Project Information, the one field cts keeps in the `.project`; a project that has one keeps it, and the view leaves it out of `Project Information.xml`, so an import never sets it: the files of a copy cannot make a project the original), writes it into the folder's `cds-text-sync.json` (`project_id`), and remembers the folder for it on this machine (`%LOCALAPPDATA%\cds-text-sync\projects.json`). A copy of the `.project` file, mailed or opened from anywhere, finds the folder again; one opened from inside a clone of the project uses that clone (several clones: the one around the file). On another machine, or before the folder is chosen, the project has no sync folder until `cts set-sync-folder` names that machine's clone once. Without a path it takes the sync folder the project file lies in, else the git repository the file lies in (a folder inside a repository cannot be a sync folder: it is a repository's root), else `<project>-cts` beside the file. A folder that names another project is refused, and so is a new folder for a project whose folder is elsewhere: that is a copy made for another plant, and `--new-id` gives it an id and a repository of its own. A copy of the folder itself, whose `cds-text-sync.json` still names the project, takes the new id the same way while this PC has the project's own folder elsewhere.

The folder becomes a git repository root, which the sync base needs: a folder without a repository gets `git init`, cts' `.gitignore` and `.gitattributes`, `cds-text-sync.json` and a first commit of those files (the line says `git=created commit=...`); a repository root that is already there only gets what is missing, uncommitted (`git=repository ignore_added=N`). A folder inside another repository, not at its root, is refused and nothing is stored; pick the repository root or a folder outside it. The refusals of the write itself (online, deny list) come first and leave the folder alone. The id changes the project in memory; `--save` saves it.

Disconnect before any project edit when the IDE is online with the PLC. Import, `set-sync-folder` and simulation mode are all refused while online, with one message: the IDE is online with the PLC; editing the project while online is not supported. Run `cts disconnect`, then repeat the command — the refusal names the exact `cts` command to retype (`cts import`, `cts set-sync-folder`, `cts project simulate on`). There is no override flag. An edit that slips through online leaves the new objects half-applied — their symbols are never exported to the running application, so every later read fails with *"is not exported to the online application"* even after a full download.

### Saving and shortcuts

Alt+Q in CODESYS opens the person's quick window; each item runs a cts command with `CTS_IDE_PID` set to that IDE: `1` Disk -> IDE (`cts import --tool`), `2` IDE -> Disk (`cts export --tool`), each merging an object both sides changed; overlapping edits first open the conflict window, where the person picks each object's side (then the row runs with `--take KEY=disk|ide`) or the merge program (`--tool`), Shift+1 / Shift+2 `cts import --force` / `cts export --force`; `3` Compare (`cts compare --tool`, `--against NAME`), `4` Switch branch (`cts checkout NAME --disk-only`, `cts branch NAME`, `cts project update`), `5` Commit the disk (`cts commit -m`: the files on disk, not the IDE, then `cts push`), `6` Commit the disk, publish (`cts commit --publish`) or, on a colleague's PC, `cts project update`, `7` Open in ... (`cts open`: the sync folder in the person's git program, `cts tool open`), `8` Settings (`cts set-sync-folder`, `cts tool`, `cts config set`), `0` More (`1` `cts fmt`, `2` the agent's activity, `3` copies `!cts --target ide-<pid> --expect-project <project> --help`, `4` `cts fsm`, `5` `cts analyze`). When the user says which digit they pressed, this is the command that ran.

`cts save` persists the open project, including changes already in memory, and
may save other pending IDE edits. Use `cts import --save` when the user asked
to apply and save folder changes. It also saves when there are no folder
changes, so it can be used as a persistence step.

Import applies to the in-memory project and does not save — saving commits everything else open in the IDE, so it is the user's call: the line says `saved=false` while the IDE holds the change unsaved. Use `--save` only when the user asked for it (it saves through the agent after a clean read-back and reports `saved=true`; a partial run never saves).

### Import

Import writes through the in-IDE agent and says the elapsed seconds. In `cts sync`, detail lines start with `disk -> IDE` or `IDE -> disk`, or `merged` for a merged change. Text objects go by objects from the sync base `refs/cts/base`: only the parts changed on disk are written (`objects.settext`, settings from the pragma), new objects are created, an object the IDE changed too is merged (`merged`), and overlapping edits are a conflict (`conflicts`, exit 2, each with its `key` and its `disk` and `ide` text; `--force` or `--take disk` writes the disk text, `--take ide` keeps the IDE text and writes it to the file, `--take KEY=disk|ide` settles one object, KEY its file or its conflict's key). An object only the IDE changed stays as the IDE has it. `cts import --force` makes the IDE the disk: every object and `.xml` object the IDE changed since the last sync, alone or with the disk, gets the disk's text (`overwritten_ide_changes`, `overwritten=N` in the line); what the IDE held goes first on `refs/cts/overwritten`, one commit per overwrite (the view with the IDE's text in those files: `git show refs/cts/overwritten:<path>`). It also creates again an object of the last sync the IDE no longer has, and deletes an object only the IDE has (a POU, GVL, DUT or interface with its members, a member added in the IDE to an object on disk, a visualization, text list or task with the objects below it; `deleted_objects`; the `delete_pou` deny key applies), after it went on `refs/cts/overwritten` in the file the export would write it to. A folder only the IDE has (no directory on disk or in the base) goes too when all its objects go; one that still holds an object the disk knows stays. An alarm group's `.csv` carries each alarm's message (`Message`, `Message (lang)` for each language of its message list): an edited message goes to the message list's row whose `TextID` is the `AlarmID`; an alarm added, removed or changed in another column refuses the import (make it in the IDE). A text list both sides changed is merged by its lines (`merged`), a row both changed is a conflict (its `key` is the `.csv`, `--take` settles it); an alarm group both changed refuses the import. A text list's rows are found by `TextID`: added rows go to the end of the IDE's list (`objects.listadd`), removed ones out (`objects.listremove`); the order of the rows does not matter, the `.csv` lists them by `TextID`. Its `.xml` has no rows: a changed or new one goes to the IDE with the `.csv`'s rows put back, so a new text list is its `.xml` and `.csv` side by side. An object with no text form (a task, a visualisation, a device, a folder's `.cds-object.xml`, the project settings) is written back whole through `objects.replace`, with an `objects.export` read-back in the normal form; one the IDE changed too is merged element by element, as git's merge of the view does (`cts hook merge-driver`): the file and the IDE get both sides' edits (`merged`; `merges: true` on its `cts compare --json` record), and only a value both changed, or a list item one removed and the other changed, is a conflict as a text object's is (its `key` is its file, `disk` and `ide` the two files; `--take` settles it, the merge program does not take it); a property of its `MetaObject` the file changed (a visualization's size, a device's identification) travels with it, a changed name does not and makes the run `partial`. When the IDE rewrites the properties on its own after the write (a Library Manager records its placeholder resolutions there when a library is added or removed), the object did land: its `.xml` takes the IDE's form and is named under `to_disk`. A rename (both files) is carried too. Deleting all of an object's files deletes the object (`objects.delete`, gated by the `delete_pou` deny key: a project that denies it refuses the whole run, the other changes too, with a `cts permissions` hint before any write). An object deleted on disk that the IDE changed since the last sync refuses the import, naming it; `--force` deletes it after the file it was in, with the IDE's text, went on `refs/cts/overwritten`. An object whose read-back is not `same` makes the run `partial`. The Library Manager (a library added or removed), the task configuration and a device go the same way. While git has view files it could not merge (a `git pull` that stopped at a conflict), `cts compare`, `cts import`, `cts sync` and `cts commit` refuse and name them: their text holds git's conflict markers. Resolve them (`git mergetool`, or edit and `git add`), `git commit`, then `cts import` carries the result.

### Import limits

`cts build` lists the errors, then the warnings, each with its `.st` file, line and column; `--json` has every message. The compile leaves out every object no task calls; `cts build --all-objects` checks those too (their messages marked `not called by any task`, `not_called` in `--json`). When errors name an unknown type or identifier (`Unknown type: 'TON'`, `Identifier 'CONCAT' not defined`) and the sync folder's Library Manager references libraries qualified-only, the answer names their namespaces (`qualified_only`): such a library's names need the prefix (`Standard.TON`), or its Qualified only property cleared. It compiles the IDE's text, not the disk's: the view files changed since the last sync and not imported yet are named under `not_imported` (a file only moved, the same bytes under another path, is not one) (`Next: cts import, then cts build`). It compiles the active application; `--app NAME` makes another one the active application first (`cts project list-devices` marks the active one with `*`), and it stays active, so `cts connect` and `cts download` act on it next.

Any other change (only some of an object's files deleted, a folder deleted or a file moved, a text object's `.xml`, an added file the agent cannot make) writes nothing: the import is refused with one line saying why, exit 1. `cts import --dry-run` and `cts compare` (`not_importable`) name it beforehand; see `cts guide import`.

A command (such as an import or a download) that times out or is interrupted (Ctrl+C, killed) stops the CLI listening, but the IDE does not stop working: the command runs to the end. A build's outcome is not lost: once it finished, `cts status` names it under `last_command` (`ok`, `errors`, `warnings`) and `cts read-log` lists its messages; the agent keeps it until the next build or until CODESYS closes. Never blind-retry an import after a timeout; wait for `cts status` to show the IDE idle, then `cts compare` says what reached the IDE.

A dialog that opens **while** a command (such as a connect or a download) runs does not cost a full timeout. The CLI asks the agent what is on screen about once a second while it waits, and a question that stays for more than two seconds ends the wait at once with exit code 3 and error code `dialog_opened` — the command is still running in the IDE, and the message carries the exact `cts dialog answer` line to get past it. Answer, then read `cts status` (`last_command`, for a build) and `cts read-log` for its messages; the reply of any other command is not kept, so check what it changed before running it again. A progress window is not a question and never ends the wait. `cts guide dialog`, `cts guide status`.

## Reading the context

The last line of every answer from the IDE names the IDE instance and its open
project, `ide-3444 · cts-reference-project` (`no project` when none is open);
`--json` carries the same as `instance` (`id`, `project.name`, `project.path`).
The id is the value `--target` takes.

`cts status` reads the PLC state and what it allows from the IDE itself; it
does not connect to the PLC:

| Field (`--json`) | Verdict line | Meaning |
|---|---|---|
| `plc.online` | `plc=online\|offline\|unknown` | Session state: `true`, `false`, or `null` when it cannot be read |
| `plc.application_state` | | Application state (`run`, `stop`) |
| `edits_allowed` | `edits=allowed\|blocked` | `true` offline, `false` while the IDE is online with the PLC (editing is then refused), `null` when the state is unknown |
| `unsaved_changes` | `unsaved=true\|false` | The IDE holds edits its project file lacks |
| `hint` | a detail line | Present only when something blocks project edits; says what to do |

`edits_allowed: null` (no `edits=` on the verdict line) is not permission: an
edit is refused then, because a blind spot must not read as permission; ask
before editing. When `edits=blocked`, run `cts disconnect` (and, if the state
does not clear, end the online session in the CODESYS IDE), then repeat the
command.

Commands that do not talk to the IDE (`cts new`, `cts guide`, `cts install`,
`cts analyze`, `cts fsm --disk`) have no such line.

Commands that talk to CODESYS accept `--timeout SECONDS`. Their default is
sized from the number of `.st` files in the sync folder's `project-view/`,
counted once by the in-IDE agent; pass `--timeout` to override it.

## Timestamps

Every timestamp a response carries (`created` in a snapshooter preset, `started_at`,
`recorded_at`) is
UTC, ISO-8601, with a trailing `Z` — `2026-10-05T20:45:12Z` — so it always
compares against another clock. Older values without a `Z` are read as they
are.

## Project Inspection and Object Changes

| Goal | Command |
|---|---|
| Read the object tree | `cts project-tree` |
| Read an object | `cts read-object` |
| Read an object's content (`.st` or XML) | `cts read-object --name X --body` |
| Create a GVL, POU or DUT | `cts new gvl\|pou\|dut <Name> [...]` |
| Create a POU member (method, action, property) | `cts new method\|action\|property <POU>.<Name> [...]` |
| Bring disk and IDE text to one state (both ways, merges) | `cts sync` |
| Lay out the IDE's Structured Text (align declarations, indent code) | `cts fmt [NAME] [--guid G] [--write] [--if-timestamp T]` |
| Lay out the sync folder's `.st` files, no IDE needed | `cts fmt --disk [NAME] [--write]` |
| Delete a POU, function, or function block | remove its `.st`, then `cts import` (deny key `delete_pou`) |

`cts import` carries `.st` files by objects through the in-IDE agent: it
writes what changed, creates what the IDE lacks (a GVL, POU, DUT or interface,
the methods, properties and actions inside a POU's file, and the folders above
them -- `objects.create`), renames a renamed file and deletes what a file no
longer holds. Without a sync base yet (a fresh clone) the IDE is the base:
what differs is written, what is missing is created, nothing is deleted. A
changed `.xml` (a task, a visualization) or text-list `.csv` goes by objects
as well, conflicts included. A new `.xml` below an object the IDE has, or at
the top of `project-view/` (the project root, as `POUs/` is for the project-level
objects export writes there, a Library Manager or Project Settings), is
imported (`objects.import`; its MetaObject `Name` must be the file's name, its
MetaObject properties come along, and a copied file takes the new GUID the IDE
gives it, wherever the file named its own); with a base, a removed one
deletes its object when nothing is below it. Any other change to those files
(a new or removed container `.cds-object.xml`, an alarm csv's columns other
than `Message`, the `.xml` of a text object's settings) refuses the import before anything is written, with
the reason; so does a sync folder that is not a git repository. A denial (the
project's `sync_import_text` deny key) names the key, with a pointer to
`cts permissions`.

The in-IDE agent enforces the project's deny list itself: an import's
deletes answer to the `delete_pou` entry and every other
agent write answers to `sync_import_text` (a save, `project.save`,
answers to `save_project`); a denial names the key, with a pointer to
`cts permissions`.

`cts fmt` runs the IDE's Structured Text through the formatter the
analyzer's indentation and alignment rules (CTS0007, CTS0008) use: variable
declarations aligned, code indented by its blocks, an `IF`/`ELSIF`
condition split at its top-level `AND`/`OR`, each statement on a line of its
own, the line endings kept. It moves whitespace only: no spaces are added
around operators (`x:=1`); that is an edit of the text. It reads
the IDE as it is, through the agent, so it needs no sync folder. Without `--write` it answers which text objects would change
(`ok fmt objects=<N> to_fix=<K> lines=<L>`, then `<label>: <n> line(s)`, a
method, property or action labelled `POU.Name`); `--json` adds every changed
object's declaration and implementation before and after, with its
`timestamp`. `cts fmt NAME` (or `POU.Name`, or `--guid G`) takes one object.
`--write` puts each changed part into the IDE through `objects.settext`
(refused while online, answering to the `sync_import_text` deny key);
`--guid G --write --if-timestamp T` writes only while the object's TimeStamp
is still `T`, so a preview a person looked at is what lands. A write that
failed makes the line `partial` with `failed=<n>` and the reason per object.
The disk follows like any IDE edit: `cts sync`, or IDE -> Disk.

`cts fmt --disk` lays out the sync folder's `.st` files instead, the same way,
and needs no IDE: what you wrote on disk is formatted before `cts import`.
Labels are the file's (`POU`, `POU.Method`), and `NAME` takes one object;
`--write` rewrites the files in place (each keeps its line ends) and leaves the
IDE alone, so `cts import` carries the new layout there. A file that cannot be
read is named in `failed`.

`cts read-object` returns identity and, for a text object, its declaration and
implementation; it is served by the in-IDE agent. Select the object by name, by `--guid`, or by `--path` — the whole tree
path or its end (`Application/MAIN`), which tells a POU from a task call of
the same name. Add `--body` to get the object's **content** byte for byte as
`cts export` writes its file: the `.st` of a POU, GVL or DUT (an FB with its
methods, properties and actions inside, and the cts pragma line when it has
one), the `.xml` of a visualization, task, device or any other object
(the `.cds-object.xml` of a folder or the Visualization Manager).
`--body-file PATH` writes it to a file instead of stdout. Use it to answer
"did my edit land in the IDE?" without writing any file.

Prefer full folder import for coordinated source changes. Use object-level mutation only when its narrower scope is intentional.

## Creating objects

`cts new` writes a new object into the project view. It is **offline** — it
needs no IDE, because it edits the disk copy of the project and
the existing sync steps carry it into CODESYS:

```
cts new gvl GVL_HMI --text 'xStart : BOOL;'   # 1. author on disk
cts compare                                   # 2. reports added=1
cts import                                    # 3. CODESYS creates it
# 4. make it reachable from a block the task calls (see below)
cts download                                  # 5. FULL download, only when the user asked for one
```

Step 3 asks the user first when it would save the IDE project — `cts import`
applies to the in-memory project, and saving commits everything else that is
open. Steps 4-5 are only needed when something must *read* the new object back
from the PLC; skip them if the object is not going to be read.

```
cts new gvl <Name> [--text T | --text-file F] [--parent PATH]
cts new pou <Name> --kind program|function|function-block [--return-type T]
cts new dut <Name> --kind struct|enum|union|alias [--base-type T]
cts new method <POU>.<Name> [--return-type T] [--text T]
cts new action <POU>.<Name> [--text T]
cts new property <POU>.<Name> [--type T] [--get-text T] [--set-text T]
```

`--text` is used **verbatim** — there is no escape processing. A literal `\n`
inside single quotes stays a backslash-n, not a line break; use bash ANSI-C
quoting (`$'x : BOOL;\ny : BOOL;'`) or `--text-file` for a multi-line body.
For a POU or a method, the `VAR … END_VAR` blocks the text starts with become
its declaration and the rest its body; blocks typed on one line are laid out a
declaration per line.

| What | Supported |
|---|---|
| `gvl` — global variable list | yes |
| `pou` — `PROGRAM`, `FUNCTION`, `FUNCTION_BLOCK` | yes |
| `dut` — `STRUCT`, `UNION`, `ENUM`, `ALIAS` | yes |
| methods, actions, properties | yes — `cts new method|action|property <POU>.<Name>` adds a block to the end of `<POU>.st`; the POU must already exist |
| SFC / FBD / LD (graphical) POUs | **no** — only textual (Structured Text) objects can be created |
| visualizations, devices, tasks, alarm configs | **no** — export them from the IDE and edit them; `cts new` only authors textual objects |

`--parent` is a project-tree path under `project-view/`, the same spelling
the `--folder` of `cts visu add` and the other screen commands takes. It defaults to the view's folder named
`Application` (the shallowest); pass it explicitly when a project has several
applications. `--parent .` is the project root, the top of `project-view/`:
the POUs view, whose objects every application shares. A shared function is
checked by tests in simulation (`cts guide tests`), not by a download.

**Only the `.st` is written, and nothing else is needed.** `cts compare` names
a `.st` object the IDE lacks as `added`, and `cts import` compares the files
with the IDE object by object, so a `.st` the IDE does not have is a new object
and is created there. Do **not** write a `.xml` next to a new `.st`: the export
writes a text object as its `.st` alone (a POU with its methods, properties and
actions in one file) and adds an `.xml` only for an object with a setting the
`(* cds-text-sync: … *)` pragma cannot carry.

**A new object reaches the PLC only if BOTH hold — reference it, then download.**

1. **It is reachable from a block the task calls.** CODESYS loads only objects
   in a task's call tree, so a GVL/POU that nothing references is compiled out
   — a full download alone does not bring it in. For an I/O GVL, mention it in
   `MAIN` or another called block, e.g. add the line

   ```
   GVL_HMI.xStart;              // or:  xLocal := GVL_HMI.xStart;
   ```

2. **A FULL download runs after that.** `cts download` is the full download; an
   import alone, or an online change, leaves the PLC's symbol table stale.

Without both, every read of a variable in the new object fails with exactly:

```
Invalid expression: 'GVL_HMI.xStart' is not exported to the online
application. It may be misspelled, not declared as a symbol, or not compiled
into the PLC.
```

An existing name is refused rather than overwritten, checked against the files
on disk. This is deliberate: CODESYS answers a duplicate
create with a modal dialog that blocks the IDE, so the
collision has to be caught here (`cts dialog answer` can answer such a dialog,
but a collision should not happen at all).

## PLC Lifecycle

| Goal | Command |
|---|---|
| Log in without changing the PLC (`--ip` points the device at it first) | `cts connect` |
| Disconnect or log out | `cts disconnect` |
| Download the application | `cts download` |
| Start or stop the application (the in-IDE agent; needs a logged-in session) | `cts start`, `cts stop` |
| Store the logged-in application on the PLC as its boot application | `cts boot-app` |
| Reset the logged-in application (origin erases it and needs `--force`) | `cts reset --kind warm\|cold\|origin` |
| Run the ST tests of the test application in simulation, or on its PLC (`cts guide tests`) | `cts test [--app NAME] [--output PATH] [--plc] [--repeat N]` |
| Whether the PLC runs the code the IDE generated last | `cts plc-crc` |
| Read the PLC runtime log, or list its loggers | `cts plc-log [--logger NAME] [--tail N]` |
| What the PLC runs: runtime, device, each application with its state and project | `cts plc info` |
| The PLC's files: list, copy to this PC, copy to the PLC | `cts plc ls [PATH]`, `cts plc get FILE [--output PATH]`, `cts plc put SRC [DEST]` |
| Remove, make or move a file or directory on the PLC | `cts plc rm PATH`, `cts plc mkdir PATH`, `cts plc mv FROM TO` |
| Extract generated `CTS\|` events as JSON | `cts plc-log --cts [--level M\|V] [--code CODE]` |

`cts download` is a full download, what the IDE's Online -> Download does, run by the in-IDE agent: the application stops and its variables start from their initial values, with no confirmation dialog. It does not need an online session first: without one it logs in (`logged_in: true` in the response), so the active application needs a reachable PLC gateway (or simulation mode). `--start 1` (the default) starts the application afterwards and `started` says so; `--start 0` leaves it stopped and does not wait for ready. The deny list key is `download`, and `start_plc` too when it starts. When the IDE held exactly the sync folder (`cts compare` clean) and the folder had nothing uncommitted (the open project's own file aside), the download records the folder's HEAD under the git ref `refs/cts/plc/<code id>` and the line says `commit=<sha>`; otherwise `commit=unrecorded` and the reason. When CODESYS saves the project on its own during the download (cts never asks it to; an older project's file then takes this IDE's format), the line says `saved=by-ide`, and so does `cts test`'s. `cts plc-crc` runs in cts.exe, reads the PLC's code id and names that commit (`commit=`, its first tag as `tag=`, its subject below the line), so "which release runs on this PLC?" has an answer after a `cts checkout v1.2` and `cts download`.

**Download finished is not application ready.** After the download the runtime needs another moment before the program runs, so `cts download` waits for that itself (default 30 s) before it returns, polling with separate short requests — the IDE stays free between them. The response adds `ready` and `ready_after_s`; when the wait failed it adds a `reason` and the command exits non-zero, so a "downloaded" that never started must not read as success. Pass `--ready-var GVL_Bench.nHeartbeat` (or any counter the task increments) to also require that variable to change between two reads — that is what proves the task is actually cycling, not just labelled run. `--no-wait` skips the wait; use it only when the caller waits itself.

When the login or download was done by hand in the IDE — or after `cts connect` — use `cts wait-ready [--var NAME] [--timeout N]` before reading variables, instead of reading immediately and racing the runtime. Do not treat a successful download or login as "the PLC is now running the new code"; wait for ready first, then read.

`cts plc-log` reads the log through the device's logger service, the device editor's Log page, not a file: a Linux runtime writes its log outside the directory the file services reach. Each entry is printed like a line of the runtime's log file, the time in UTC. With `--cts`, an empty result with no malformed records says that ST code must log the `CTS|` marker to write records (the `cts test` test application does) and points to `cts plc-log --tail N` for the raw log. Neither it nor `cts plc` logs in: each connects to the device for its run, so they work while the IDE is offline, and a login stays as it was. `cts plc info` names the project each application on the PLC was downloaded from, without the login a `cts plc-crc` needs. `cts plc get` and `cts plc put` check the copy against the CRC32 the PLC computes for its file (`crc32=` on the line; `unchecked` with the reason when the device does not give one). `put`, `rm`, `mkdir` and `mv` change the PLC's files and answer to the deny list key `plc_upload`, denied by default; `info`, `ls` to `plc_files`, `get` to `plc_fetch`.

PLC paths (the arguments of `cts plc`, except `put`'s SRC) name files on the device, not on this PC, and are sent exactly as typed: a leading `/` does not survive Git Bash, whose MSYS layer rewrites it into a Windows path before `cts` even runs (the agent then refuses it with that hint). Pass `.` — or nothing, to `cts plc ls` — for the PLC root, or set `MSYS_NO_PATHCONV=1`. Host paths are the opposite: `put`'s SRC and `get`'s `--output` are paths on this PC, made absolute before they are sent.

## Variables

| Goal | Command |
|---|---|
| Read one expression or several | `cts read NAME [NAME ...] [--file F]` |
| Watch values move | `cts read NAME [NAME ...] --samples N [--interval S]` |
| Wait for a value | `cts read NAME --until VALUE [--interval S] [--within S]` |
| Write one expression, or several in one PLC cycle | `cts write NAME VALUE [NAME VALUE ...]` |
| List preset leaves | `cts snapshooter tree [--path PREFIX]` |
| Read a JSON preset | `cts snapshooter take [--path P] [--prefix P] [--paths-file F] [--label L] [--out FILE]` |
| Diff a preset against the PLC | `cts snapshooter diff --input PRESET.json` |
| Restore a preset (dry-run unless `--apply`) | `cts snapshooter restore --input PRESET.json [--apply]` |

`cts read` shows a value the way the IDE spells it: `WORD#5`, `REAL#1E-05`, `TRUE`, `'text'`, `E_Mode.Run`. If a name is unknown to the PLC, the error suggests the closest declared names from the sync view (`did you mean: GVL.fbMotor1.tFbTimeout`). `cts write` takes an IEC literal for the variable's type, read by the IDE's own parser — `5`, `16#FF`, `WORD#7`, `1.5`, `TRUE`, `T#2s`, `'text'`; a STRING also takes bare text, an enum its member as `E_Mode.Run`, `Run` or `E_Mode#Run` — then reads the value back and reports `confirmed` (`written_as` shows the IDE's spelling when it differs from what you typed, e.g. `16#FF` -> `WORD#255`). A value the type cannot hold fails with the IDE's reason. Several `NAME VALUE` pairs are written together, in one PLC cycle (the IDE's Write Values), and each is read back; a value that cannot be written writes none of them. Several names (or `--file`, one per line) are read in one call and answer a row per name in the order given, `read_ok` with the value or `read_error` with the reason. A structure, array or FB instance is read as its leaf members, a row each (the names `cts snapshooter tree` lists). `--samples N` reads them N times, `--interval` seconds apart (Ctrl+C stops early with what was read); the answer lists the first sample and then only the values that changed, each at its time since the first read, and `--json` has every sample. `--until VALUE` reads one name until it shows that value (spelled as for `cts write`), for at most `--within` seconds (default 30), and exits 2 when it did not come. Both are served by the in-IDE agent and only use a session that is already logged in (`cts connect`).

Keep restore in dry-run mode unless the user explicitly requests application.

`snapshooter` keeps values in a JSON preset (`take` writes a document of
`{path, type, value, read_ok}` with a `meta` block, `diff`/`restore` read it
back; presets of the former CODESYS Snapshooter dialog load too). Every action
runs through the in-IDE agent: the variables are the ones the programs and GVLs in the IDE declare
now (unsaved edits included), FB instances and structures expanded to their
leaves. Nothing is cached, so an edit shows up on the next call.

### What each snapshooter action needs

| Action | Needs | Notes |
|---|---|---|
| `tree` | a project open in the IDE; **no** PLC session | reads the declarations; no value is read |
| `take`, `diff`, `restore` | an existing **online session**, even in dry-run | they read live values; without a session they answer `Not connected` — run `cts connect`, or log in in the CODESYS UI first (a read uses a session but never logs in itself) |

Values are read through the online application's **symbols**, so a leaf that is
not exported (an object not declared as a symbol, or code not compiled into the
PLC) comes back `read_ok: false` with *"is not exported to the online
application"* in `read_error` — that is a per-variable result, not a command
failure. A whole struct or array is not one value: it comes back `read_ok: false`
naming its type; read its members (`GVL.st.x`) or elements (`GVL.a[1]`).

`--path` on `tree` is a **case-sensitive prefix** of the leaf path — a plain
string prefix, **not a segment boundary**: `--path GVL` matches both `GVL.a` and
`GVL_HMI.x`. To pin one GVL, include the dot: `--path 'GVL.'`. It is not a glob
(no `*`/`?` expansion). `--path` on `take` is an exact path and is repeatable;
`--prefix` on `take` takes every leaf under a prefix, under the same plain
case-sensitive string rule as `tree --path` (an exact `--path` inside it is not
duplicated). A `--prefix` that matches no leaf is an error.

`restore --apply` writes every eligible value in one `vars.write` call, so the
deny list's `write_variable` rule decides per variable; a refused or failed
write is counted in `skipped` with its cause. An entry is not written when it
was not read when saved or cannot be read now; one whose type changed is
still written, with a warning.

**File paths.** `--out`, `--input` and `--paths-file` are opened by `cts`
itself, so a relative path resolves against the directory you ran `cts` in.

Output is one JSON object per action (`--pretty` renders it as text):

| Action | Envelope |
|---|---|
| `tree` | `{action, path, count, leaves[{path,type}]}` |
| `take` | `{action, label, count, document{meta,variables}, saved_to?}` |
| `diff` | `{action, count, report{identical,same,missing,type_changed,value_changed}}` |
| `restore` | `{action, applied, result{written,skipped,warnings,would_write,details}}` |

## Static Analysis

| Goal | Command |
|---|---|
| Run the offline analysis | `cts analyze` |
| List rules | `cts analyze rules` |
| Show one rule's docs | `cts analyze explain CTS0001` |
| Manage the baseline | `cts analyze baseline create\|update\|check` |
| Apply suppress/fix-later decisions | `cts analyze triage --apply decisions.json` |
| Validate a generated screen (geometry, members, colours, overlaps) | `cts visu check --screen NAME` |

`cts analyze` runs offline over `project-view/` — it never talks to the IDE.
`--rule CTSxxxx` restricts to one rule (repeatable); `--fail-on` sets the exit-1
threshold (`danger`/`suspicious`/`style`); `--incomplete error` makes partial
runs exit 3; `--sarif FILE` also writes SARIF 2.1.0. Exit codes: 0 passed, 1
findings at/above `--fail-on`, 2 settings or startup error, 3 incomplete. Some
rules are opt-in and disabled by default. Settings live in `cds-text-sync.json`
under `"analyze"`: `fail_on`, `incomplete`, `rules.<ID>.enabled`/`severity`/
`options`, `scopes[{path, enabled, exclude}]`. State lives in `.cts-analyze/`
(baseline.json, suppressions.json, session.json); source files opt out with
`// cts:ignore-file CTS0001 -- reason`.

## Project Documentation

`cts docs` writes `.cts-docs/` beside the project view, offline: read `index.md` first, then `project/<Name>.md` for an object (interface, inherited members, methods/properties/actions, calls, callers, tasks, globals read and written) and `libraries/<Name>-<Version>.md` for a referenced library's LibDoc (signature, description, example, interface). `symbols.jsonl` is one JSON line per symbol, to search. A library without LibDoc of the referenced version is listed under Missing LibDoc with the reason; another version never stands in. CODESYS writes LibDoc only for a library whose Project Information sets `DocFormat = reStructuredText` (`plain_text_library` otherwise), and only once a Library Manager of an IDE with Library Documentation Support shows it (`libdoc_not_generated` until then). `--libraries DIR` (default `C:\ProgramData\CODESYS`), `--out DIR`, `--check` (exit 0 fresh, 1 stale, 2 no bundle). `--show NAME` prints one library symbol's page instead and writes nothing: `TON`, `Standard.TON` or `NBS.TCP_Client` (by namespace or library name), with the methods documented below it; a library's or namespace's name alone prints all of it; no match names the symbols that hold the name and the referenced libraries with no pages, with why (exit 1).

`cts lib` lists the library references of each `Library Manager.xml` in the sync folder (namespace, library, placeholder, `qualified-only`), offline; a direct reference to version `*` names the newest version installed on this PC (`* is 3.5.20.0 here`), which CODESYS loads even when another, newer CODESYS on the PC installed it. `cts lib set NAME --qualified-only on|off`, `cts lib add "Name, Version (Vendor)" --namespace NS [--qualified-only] [--placeholder NAME]` and `cts lib remove NAME` edit those files, only the lines of that reference; NAME is the library's name, its placeholder or its namespace, `--app` picks one application's manager. `--placeholder` references the library through a placeholder, so the device picks its version (`--placeholder "CAA NetBaseSrv"` for CAA Net Base Services). A project with no Library Manager (a new library) gets one at its root (`POUs/Library Manager.xml`) from its first `cts lib add`. `cts import` then loads the change in the IDE and names a library that does not load. A build whose errors name unknown types or identifiers says which libraries are qualified-only.

## FSM Transition Maps

| Goal | Command |
|---|---|
| The state machines in the IDE's Structured Text | `cts fsm` |
| One object's machines, every transition | `cts fsm NAME` |
| The same from the sync folder's files, no IDE | `cts fsm --disk [NAME]` |
| A machine as a mermaid stateDiagram | `cts fsm NAME --mermaid` |

`cts fsm` finds the `CASE` state machines in the IDE's Structured Text through
the agent (unsaved edits included): a line per machine with its states and
transitions; for one object (`NAME` or `Parent.Name`) each transition with its
condition and line, in source order (the order `IF`/`ELSIF` branches are
tested), and what looks wrong (a state never entered or without a way out, a
value no branch handles). `--disk` reads the `.st` files of the sync
folder (`--sync-folder` names another) and needs no IDE; its lines are the
file's and each object names its `file`. `--json` gives every machine's states
and transitions with the code behind them; `--layout` adds the GRAFCET geometry
the agent's FSM window draws (Alt+Q, `0`, `4`). Text without a machine is not
an error; an unknown `NAME` is refused.

## Tests and Escape Hatch

| Goal | Command |
|---|---|
| Run the ST tests of the test application in simulation (`cts guide tests`) | `cts test` |
| Run JSON test plans (`cts guide tests`) | `cts verify --with-test` |
| Call an IDE method directly | `cts raw` |

Inspect nested help before using these commands. Use `raw` only when the normal CLI does not expose the required supported operation.
`cts raw METHOD [--key value ...]` runs in cts.exe and sends one agent method directly. Values that parse as JSON are sent as their JSON values; other values stay strings. The agent's result is printed as JSON. Without METHOD, it lists the agent's methods. `--timeout SECONDS` sets the wait (default 15). Relative `--input`, `--output`, `--out`, and `--src` paths resolve from the current working directory.

## Output

- The default output starts with one verdict line, `<ok|partial|error> <command> key=value ...`, then what to act on (the changed objects, the build errors, the dialog), then `ide-<pid> · <project>`. A failure names the cause on that line and ends with `Next: <command>` when cts knows the fix. A command that cannot reach the IDE answers the same way: `error connect cause="no in-IDE agent answers"`, `Next: cts project open --path <p> --launch`.
- `--json` (or `--output json`) prints the full machine payload, and nothing else — use it when parsing.
- `--pretty` or `--output text` prints the human-readable dump of the whole payload.
- `cts raw` is the escape hatch: it always prints the IDE's own payload.
- Preserve raw error details when reporting failures.
