// `dialog.answer`: read the dialog on screen, check the caller's names against
// it, set the choices, press the button, and watch it go away.
//
// The order is the whole design:
//
//   1. pick the dialog the caller meant, from the id it read (`--id`), or the
//      only one on screen;
//   2. on the dialog's thread (the UI thread, or the thread that showed it),
//      re-read it *live* and resolve every name against that
//      fresh read -- a stale id, an option that is not there, a button name
//      that matches two controls: all refused before anything is touched;
//   3. set the options and read them back; a choice that does not stick is
//      refused too, still without pressing anything;
//   4. *post* the press to the UI thread's queue and return, so a handler that
//      opens the next dialog (Clean All -> login) cannot trap this call inside
//      its modal loop;
//   5. wait, on this thread, for the pressed window to leave the screen, and
//      report what replaced it.
//
// Step 2 is the only place a command ever runs on a blocked UI thread, and it
// is safe for exactly that reason: it reads and sets controls, which is what
// the dialog is waiting for, and it delegates the click to the queue the modal
// loop is already pumping.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;

namespace Cts.Agent
{
    internal sealed class DialogAnswerer
    {
        //: The UI thread is pumping inside the modal loop, so the call starts
        //: at once; the budget is only there for a genuinely wedged IDE.
        const int UiTimeoutMs = 3000;

        //: How long to wait for the pressed dialog to go away.  A dialog that
        //: is answered disappears in milliseconds; five seconds is a boundary,
        //: not a wait anybody pays.
        const int DefaultWaitMs = 5000;
        const int MaxWaitMs = 15000;
        const int PollMs = 25;

        readonly Ide _ide;
        readonly ModalState _modal;
        readonly ModalWatcher _watcher;
        readonly IModalProbe _probe;
        readonly FileLog _log;

        public DialogAnswerer(Ide ide, ModalState modal, ModalWatcher watcher, IModalProbe probe, FileLog log)
        {
            _ide = ide;
            _modal = modal;
            _watcher = watcher;
            _probe = probe;
            _log = log;
        }

        public Dictionary<string, object> Run(Request request)
        {
            var asked = DialogRequest.Parse(request);
            var target = Pick(_modal.Current, asked);
            var waitMs = (int)Math.Max(200, Math.Min(MaxWaitMs, request.Int("timeout_ms", DefaultWaitMs)));

            var applied = _watcher.OnUiThread(target.Hwnd)
                ? _ide.OnUiUnguarded("dialog.answer", UiTimeoutMs, () => Apply(target, asked))
                : ApplyOffUi(target, asked);

            double seconds;
            bool covered;
            var closed = WaitForClose(target, waitMs, out seconds, out covered);
            // One fresh look before reporting what is on screen now: the state
            // is a 500 ms poll and would still name the dialog just closed.
            _probe.ConfirmModal();
            var next = Next(target.Hwnd);

            var result = new Dictionary<string, object>(applied);
            result["closed"] = closed;
            result["closed_after_s"] = Math.Round(seconds, 3);
            result["covered"] = covered;
            result["next"] = next;

            _log.Write("dialog.answer: id=" + result["id"]
                + " via=" + result["via"]
                + " pressed='" + result["pressed"] + "'"
                + " chose=[" + string.Join(", ", ToStrings(result["chosen"])) + "]"
                + " cleared=[" + string.Join(", ", ToStrings(result["unchecked"])) + "]"
                + " closed=" + (closed ? "yes" : "no") + " after " + result["closed_after_s"] + "s"
                + (next == null ? "" : " next=" + DescribeNext(next)));

            // A press that did not close the dialog is not an error here (a
            // "Details..." or "Apply" button does not close anything), so it is
            // reported and left to the caller.
            return result;
        }

        // ── picking the dialog ───────────────────────────────────────────────

        // The dialog the caller meant: the one with that id, or the only one.
        // Never a guess -- several open dialogs and no id is refused.
        static ModalWindow Pick(IReadOnlyList<ModalWindow> open, DialogRequest asked)
        {
            var windows = open ?? new List<ModalWindow>();

            if (!string.IsNullOrEmpty(asked.Id))
            {
                var matched = new List<ModalWindow>();
                foreach (var window in windows)
                    if (window.Fingerprint == asked.Id) matched.Add(window);
                if (matched.Count == 1) return matched[0];
                if (matched.Count == 0)
                    throw new ProtocolException(ErrorCodes.DialogChanged,
                        "no dialog with id " + asked.Id + " is open"
                        + (windows.Count == 0 ? "" : "; the dialog on screen is id " + windows[0].Fingerprint),
                        Details(windows));
                throw new ProtocolException(ErrorCodes.BadParams,
                    matched.Count + " dialogs have id " + asked.Id + "; read them again", Details(windows));
            }

            if (windows.Count == 0)
                throw new ProtocolException(ErrorCodes.DialogChanged,
                    "no modal dialog is open in this IDE, so there is nothing to answer");
            if (windows.Count > 1)
            {
                var ids = new List<string>();
                foreach (var window in windows) ids.Add(window.Fingerprint);
                throw new ProtocolException(ErrorCodes.BadParams,
                    windows.Count + " dialogs are open (" + string.Join(", ", ids.ToArray())
                    + "); pass id=<fingerprint> to say which one to answer", Details(windows));
            }
            return windows[0];
        }

        // A dialog another thread shows: a Windows Forms one is answered on its
        // own thread, through its form; a native one (#32770, a MessageBox) is
        // read and pressed with Win32 alone, which any thread may do.  The UI
        // thread is no help here: it may be the one waiting for that thread.
        Dictionary<string, object> ApplyOffUi(ModalWindow target, DialogRequest asked)
        {
            var form = System.Windows.Forms.Control.FromHandle(new IntPtr(target.Hwnd));
            if (form == null) return Apply(target, asked);
            return UiCall.Run(action => form.BeginInvoke(action), () => Apply(target, asked),
                UiTimeoutMs, "dialog.answer", null, StartTimeout.DefaultMs);
        }

        // ── on the dialog's thread: validate, set, verify, press ─────────────

        Dictionary<string, object> Apply(ModalWindow picked, DialogRequest asked)
        {
            var live = WindowReader.ReadLive(new IntPtr(picked.Hwnd));
            if (live == null || live.Window == null || !WindowReader.Showing(picked.Hwnd))
                throw new ProtocolException(ErrorCodes.DialogChanged,
                    "the dialog closed before it could be answered");

            // The snapshot the caller acted on is checked against the live read
            // inside Resolve: the fingerprint, then every name.
            var plan = DialogResolver.Resolve(live.Window, asked);

            foreach (var caption in plan.Choose) SetOption(live, caption, true);
            foreach (var caption in plan.Uncheck) SetOption(live, caption, false);

            var via = PressButton(live, plan.Press);

            var result = new Dictionary<string, object>
            {
                { "answered", true },
                { "id", live.Window.Fingerprint },
                { "pressed", ModalCaption.Display(plan.Press) },
                { "chosen", Display(plan.Choose) },
                { "unchecked", Display(plan.Uncheck) },
                { "via", via },
            };
            return result;
        }

        // Set one option and read it back.  A control the agent cannot resolve
        // never reaches here (it is a button, not an option), and a state that
        // does not stick is a refusal -- the caller asked for something the
        // dialog would not do, so pressing a button on top of it would be worse
        // than doing nothing.
        void SetOption(LiveDialog live, string caption, bool wanted)
        {
            var control = live.Find(caption);
            if (control == null)
                throw new ProtocolException(ErrorCodes.DialogChanged,
                    "'" + caption + "' is not there any more", Details(live.Window));

            if (control.Checked.HasValue && control.Checked.Value == wanted) return;

            var framework = control.Control as System.Windows.Forms.Control;
            if (framework == null)
                throw new ProtocolException(ErrorCodes.Unavailable,
                    "cannot set '" + caption + "': the agent has no Windows Forms control for it",
                    Details(live.Window));

            if (!ControlReader.SetState(framework, wanted))
                throw new ProtocolException(ErrorCodes.BadParams,
                    "cannot clear '" + caption + "': it is a radio button, and a radio is cleared by choosing another option",
                    Details(live.Window));

            _log.Write("dialog.answer: set '" + caption + "' " + (wanted ? "on" : "off")
                + ": " + ControlReader.Describe(framework));

            var after = ControlReader.Checked(framework);
            if (after.HasValue && after.Value != wanted)
                throw new ProtocolException(ErrorCodes.DialogChanged,
                    "the dialog did not keep '" + caption + "' " + (wanted ? "selected" : "cleared")
                    + " (it is now " + (after.Value ? "selected" : "cleared")
                    + "); nothing was pressed. Setting two options of one group in a single answer does this.",
                    Details(live.Window));
        }

        // Post the click; do not wait for it.  The UI thread runs it when its
        // modal loop gets to it, which is the only way a handler that opens a
        // dialog of its own can be survived -- and the close wait below is what
        // proves the press was taken.
        string PressButton(LiveDialog live, string caption)
        {
            var control = live.Find(caption);
            if (control == null)
                throw new ProtocolException(ErrorCodes.DialogChanged,
                    "the button '" + caption + "' is not there any more", Details(live.Window));

            var framework = control.Control as System.Windows.Forms.Control;
            if (framework != null)
            {
                // The log records what the press really did, and what the
                // control really is: this is the place that says whether the
                // click went through Windows Forms or through Win32.
                _log.Write("dialog.answer: pressing '" + caption + "': "
                    + ControlReader.Describe(framework));
                if (ControlReader.PostClick(framework)) return "winforms";
            }
            if (Win32.Click(new IntPtr(control.Hwnd))) return "wm_command";

            throw new ProtocolException(ErrorCodes.Internal,
                "could not press '" + caption + "': neither the control nor its window accepted a click");
        }

        // ── waiting for the answer to be taken ───────────────────────────────

        // True when the window left the screen within the budget.  The clock is
        // returned either way: "how long until it went away" is the measurement
        // that says the press worked.  A dialog the press opened on top of it
        // (Set All to Newest -> "set to newest:" [OK]) ends the wait too: the
        // pressed one cannot close before that one is answered.
        bool WaitForClose(ModalWindow target, int waitMs, out double seconds, out bool covered)
        {
            var clock = Stopwatch.StartNew();
            covered = false;
            while (clock.ElapsedMilliseconds < waitMs)
            {
                if (!WindowReader.Showing(target.Hwnd)) break;
                if (Newer(target)) { covered = true; break; }
                Thread.Sleep(PollMs);
            }
            clock.Stop();
            seconds = clock.Elapsed.TotalSeconds;
            return !WindowReader.Showing(target.Hwnd);
        }

        bool Newer(ModalWindow target)
        {
            foreach (var window in _modal.Current)
                if (window.Id > target.Id) return true;
            return false;
        }

        // What is on screen now, other than the dialog that was answered: the
        // usual case is the next dialog CODESYS chained behind it.
        object Next(long answeredHwnd)
        {
            var list = new List<object>();
            foreach (var window in _modal.Current)
                if (window.Hwnd != answeredHwnd) list.Add(window.ToData());
            return list.Count == 0 ? null : list;
        }

        // ── small helpers ────────────────────────────────────────────────────

        static Dictionary<string, object> Details(ModalWindow dialog)
        {
            return DialogResolver.Dialogs(dialog);
        }

        static Dictionary<string, object> Details(IReadOnlyList<ModalWindow> dialogs)
        {
            var list = new List<object>();
            foreach (var window in dialogs) list.Add(window.ToData());
            return new Dictionary<string, object> { { "dialogs", list } };
        }

        static string[] Display(string[] captions)
        {
            var shown = new List<string>();
            foreach (var caption in captions) shown.Add(ModalCaption.Display(caption));
            return shown.ToArray();
        }

        static IEnumerable<string> ToStrings(object value)
        {
            var list = value as IEnumerable<string>;
            return list ?? new string[0];
        }

        static string DescribeNext(object next)
        {
            var list = next as List<object>;
            if (list == null || list.Count == 0) return "none";
            var parts = new List<string>();
            foreach (var item in list)
            {
                var data = item as IDictionary<string, object>;
                object title;
                if (data != null && data.TryGetValue("title", out title)) parts.Add(Convert.ToString(title));
            }
            return string.Join(", ", parts.ToArray());
        }
    }
}
