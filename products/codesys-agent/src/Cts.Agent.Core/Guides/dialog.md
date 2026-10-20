# Dialogs

A modal CODESYS dialog stops everything else in the IDE: a command that needs
the IDE runs on its UI thread, so while a dialog is on screen none can run. The
agent's pipe does not need that thread, which is why `cts ping` still answers
and `cts` can tell you exactly what is blocking the IDE.

```sh
cts dialog           # what is on screen right now: ok dialog dialogs=0
cts dialog --json    # the raw agent reply, structured
cts dialog answer --choose "<option>" --press "<button>"
```

Both commands are answered off the UI thread, so they work precisely when
everything else is refused.

A question the IDE showed while a command ran, and that went away before
anyone answered it (CODESYS closes some on its own, an error box among them),
is named under the command's line, once each, as `dialog seen meanwhile [id
...]: ...`, and under `dialogs_seen` in `--json`; a failed command names it on
its error output. A progress window is part of the command and is not named.

## The verdict line, then the dialog

```
ok dialog dialogs=1 id=3f9a1c02 title=CODESYS
blocked by a dialog [id 3f9a1c02]: CODESYS - The application changed since last
download. What do you want to do? - options: (*) Login with online change,
( ) Login with download, ( ) Login without any change, [ ] Update boot
application - buttons: [OK] [Cancel] [Details...]
```

`dialogs=0` is the answer that lets the next command run; `dialogs=1` names the
one dialog that is blocking the IDE. Everything after the first line is the
dialog itself:

- **the id** is a short fingerprint of the dialog: its title, its text and its
  control captions. The same dialog keeps the same id across polls and even
  across an IDE restart; a different question gets a different one. It is what
  `--id` matches against, and it is not the window handle: handles change,
  and they say nothing about the question being asked.
- **options** are the radio buttons `(*)` / `( )` and the check boxes
  `[x]` / `[ ]`, each with its state. `?` inside means the agent could not read
  that state.
- **buttons** are the push buttons, in the order the dialog holds them.

A command that cannot start because a dialog is open exits 3. Its status says
`cause=dialog_blocked`, and `Next:` gives the ready `cts dialog answer ...` line
for the dialog. The error says the command did not run; the `blocked by a
dialog ...` line follows once as a note. If the refusal has no dialog snapshot,
`Next:` is `cts dialog`.

## Answering it

```sh
cts dialog answer --choose "Login without any change" --press OK
cts dialog answer --uncheck "Update boot application" --press OK
cts dialog answer --id 3f9a1c02 --choose "Login with download" --press OK
```

`--choose` selects a radio button or ticks a check box, `--uncheck` clears a
check box, `--press` is the button that submits the answer. Names are matched
exactly, but not fussily: case is ignored and the `&` of a mnemonic is
optional, so `--press OK` matches a button captioned `&OK`. There are no
defaults and no guessing — a name that is not on the dialog is an error.

The agent re-reads the dialog first and checks everything against that fresh
read. If a name is not there, matches two controls, or `--id` no longer matches
the dialog on screen, it **refuses and clicks nothing**, printing the dialog as
it is now so the next attempt needs no extra round trip. The options are read
back before anything is pressed; a choice that did not stick is refused too.

The reply says what happened and what came next:

```
ok dialog-answer closed=true pressed=OK id=3f9a1c02
answered [id 3f9a1c02]  pressed [OK] (winforms)  chose: Login without any change  the dialog closed after 0.03 s
```

A press that did not stick reads `partial dialog-answer closed=false ...`, so
the first line alone tells you the dialog is still there. A button that opens
another dialog on top of its own (`Set All to Newest` -> "The following items
have been set to newest" [OK]) says so at once — "another dialog opened on top"
— and lists that dialog first: answer it, then the one under it if it stays.
With several dialogs open, `cts dialog` names the newest first, the one that
takes the input.

`next` (in `--json`) carries the dialog that replaced the one answered — dialog
chains are normal (`Clean All` leads to a login question). Exit code 0 means the
dialog left the screen; 1 means it is still there after the wait, or the answer
was refused.

A press is delivered to the UI thread's own queue and then verified by watching
the window close, which is why a button that opens another dialog is handled
rather than hanging.

## A dialog that opens in the middle of a command

A command can be sent while the IDE is clear and reach a question part-way
through. The command runs on the UI thread, so it does not return until the
dialog is answered — without help the CLI waits out the command's whole budget
(60–180 s) and then says only "check CODESYS for a modal dialog".

Instead the CLI watches for it. While it waits for a command's reply it asks
the agent — about once a second, never the UI thread — what is on screen, and a
question that **stays** for more than two seconds ends the wait right then:

```sh
cts connect
# ~2 s later, instead of the full timeout:
#   error connect_to_device cause=dialog_opened
#   Next: cts dialog answer --id 3f9a1c02 --choose "Login with online change" --press "OK"
# and on stderr the dialog itself, in the one-line form:
#   blocked by a dialog [id 3f9a1c02]: CODESYS - The application changed since
#   last download. What do you want to do? - options: ... - buttons: [OK] [Cancel]
#   The command (connect_to_device) is still running inside the IDE; it finishes
#   once the dialog is answered, but its reply is not kept.
```

The wait ends, the command does not: it is still running inside the IDE, and
the reply says so. Answer the dialog with the line printed — it is built from
that dialog's own captions, so it can be run as it stands — then read the
outcome:

- **Exit code 3** and error code `dialog_opened`. That is "incomplete", the same
  code `cts analyze --incomplete error` uses, not a failure: nothing broke, the
  IDE is waiting on a question. `--output json` puts the whole snapshot on
  stdout in the `cts dialog --json` shape, under `dialogs`, with `command`
  naming the method that was waiting.
- A build keeps its outcome: **`cts status`** reports it under `last_command`
  (`method`, `ok`, `errors`, `warnings`, `recorded_at`) once it finished, and
  **`cts read-log`** lists its messages.
- Any other command answers only the caller that stopped waiting,
  so the message says its reply is not kept: check what it changed before
  running it again.

Two things keep the watch quiet. It only ends the wait on a **question** — a
progress window (a bar with a lone Cancel) is part of the command and is
ignored, so a build or a download is never interrupted by its own progress
window. And a window has to **stay**: one that flashes past belongs to the
command too. When no agent answers, the watch simply does not run and the
command behaves as it always did.

While that command is still running in the IDE, another command that needs
the IDE's UI thread is refused at once with `busy` ("the IDE is still running
app.build from an earlier command") rather than queued behind it or run inside
it; `cts status` and `cts dialog` keep answering. Run it again once `cts status`
shows the IDE idle.

## When cts cannot help

- **No agent.** `cts dialog` needs the in-IDE agent. Without it, there is
  nothing that can read the dialog while the IDE is stuck — answer it in the IDE
  by hand. (`cts project open --launch` and the `cds-text-sync` menu entry both
  start the agent.)
- **A control the agent cannot reach.** CODESYS draws its message boxes with
  Windows Forms, and the agent can read and operate those controls. A dialog
  drawn some other way still reports its title, text and buttons, but its
  options come back empty — the buttons can still be pressed by name.
- **The dialog is not really a question.** A progress window or a long import
  is not a modal dialog; `cts dialog` says `ok dialog dialogs=0` for those, and
  the IDE is simply busy.

## A note on which dialogs appear

`cts`'s own work does not raise this dialog: `download`, `connect` and `build`
choose their online-change option explicitly, so no "The application changed
since last download" question appears for them. What appears is what a **person
or the IDE** opened — typically Online > Login in an IDE somebody is using, or a
confirmation for a project edit made by hand. Answering it from `cts` is what
lets an unattended session past a question nobody is there to click.
