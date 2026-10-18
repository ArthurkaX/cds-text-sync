// The refusal side of modal detection: which requests the agent still answers
// while a dialog is open, and the structured error it refuses the rest with.
//
// The design is: the methods that do not need the
// IDE's UI thread always answer, so a client can always ask "what is on
// screen?" and "are you alive?"; everything else is refused up front, because
// while a modal is up it would either wait forever or -- worse -- run nested
// inside the dialog's modal loop.
using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    public static class ModalGate
    {
        // Methods that stay available while a modal is open:
        //   ping, methods, subscribe/unsubscribe/subscriptions
        //     never touch the IDE at all;
        //   hello, state
        //     ask the UI thread with a deadline but must always answer, so a
        //     blocked IDE still looks alive rather than dead;
        //   dialog.probe
        //     reads the watcher's snapshot from another thread, not the UI
        //     thread; it is what tells the CLI "blocked by a dialog" instead of
        //     a 30 s timeout, so it has to answer precisely while one is up;
        //   dialog.answer
        //     exists for exactly this state: it reads the dialog's controls,
        //     sets them and posts the press to the UI thread's own queue, which
        //     is pumping inside the modal loop -- being refused here would make
        //     it impossible to answer the very dialog it is about;
        //
        // Everything else -- vars.read and vars.write (both need the UI thread)
        // and any future method -- is refused with dialog_blocked.  The list is
        // deliberately an allowlist: a new method is blocked by default, which
        // is the safe way to be wrong.
        static readonly HashSet<string> Always = new HashSet<string>(StringComparer.Ordinal)
        {
            "ping",
            "hello",
            "state",
            "methods",
            "subscribe",
            "unsubscribe",
            "subscriptions",
            "dialog.probe",
            "dialog.answer",
            "project.status",
        };

        public static bool AnswersWhileModal(string method)
        {
            return method != null && Always.Contains(method);
        }

        // The router gate's decision, with the confirm step.  Returns the error
        // to answer with, or null to let the request run.
        //
        // A cached "modal open" is not trusted on its own: the snapshot is a
        // 500 ms poll, so the first command after the user dismisses a dialog
        // would otherwise be refused once, naming a dialog that no longer
        // exists.  Before refusing we ask for one fresh look;
        // if it finds nothing, the snapshot was stale and the request proceeds.
        // The snapshot is not confirmed on the "not modal" path -- a normal call
        // pays nothing extra.  `probe` may be null (no live look available):
        // then a cached "modal open" is trusted, which is the fail-closed way.
        public static ProtocolException Check(string method, ModalState modal, IModalProbe probe)
        {
            if (modal == null || AnswersWhileModal(method)) return null;
            if (!modal.AnyOpen) return null;
            var open = probe == null || probe.ConfirmModal();
            return open ? ModalErrors.Blocked(modal.Current) : null;
        }

        // Requests that never hold the UI thread themselves: the Debug build's
        // widget.drive and widget.snapshot (QuickWidget) post short steps to it
        // and wait between them, and the cts runs the window starts must reach
        // the agent while a drive waits for them; test.run calls the agent's
        // own methods step by step (test.app too), and each of those takes the
        // thread itself.
        static readonly HashSet<string> NotHolding = new HashSet<string>(StringComparer.Ordinal) { "widget.drive", "widget.snapshot", "test.run", "test.app" };

        // A request that needs the UI thread while another one still runs on
        // it is refused rather than queued behind it or run nested in its
        // message pump (a second build inside a first one breaks the
        // compiler until the IDE restarts). *running* names every request
        // being answered, this one included, longest-running first.
        public static ProtocolException CheckBusy(string method, IEnumerable<string> running)
        {
            if (AnswersWhileModal(method) || NotHolding.Contains(method)) return null;
            var held = running.Where(name => !AnswersWhileModal(name) && !NotHolding.Contains(name)).ToList();
            if (held.Count < 2) return null;
            return new ProtocolException(ErrorCodes.Busy,
                "the IDE is still running " + held[0] + " from an earlier command; wait for it (cts status) and run this again");
        }
    }

    public static class ModalErrors
    {
        // The structured refusal: code dialog_blocked, a compact human snapshot
        // in the message, and the full windows in error.data.dialogs.
        public static ProtocolException Blocked(IReadOnlyList<ModalWindow> dialogs)
        {
            var windows = dialogs == null ? new List<ModalWindow>() : new List<ModalWindow>(dialogs);
            var list = new List<object>();
            foreach (var window in windows) list.Add(window.ToData());

            return new ProtocolException(ErrorCodes.DialogBlocked, BlockLine(windows),
                new Dictionary<string, object> { { "dialogs", list } });
        }

        // A dialog opened and closed while a call waited for the UI thread: the
        // call did not run (its world changed), and nothing is open now.  Code
        // dialog_blocked still, with the closed windows in error.data.gone.
        public static ProtocolException CameAndWent(IReadOnlyList<ModalWindow> gone)
        {
            var list = new List<object>();
            foreach (var window in gone) list.Add(window.ToData());
            return new ProtocolException(ErrorCodes.DialogBlocked, GoneLine(gone),
                new Dictionary<string, object> { { "dialogs", new List<object>() }, { "gone", list } });
        }

        public static string GoneLine(IReadOnlyList<ModalWindow> gone)
        {
            var parts = new List<string>();
            foreach (var window in gone) parts.Add(window.Snapshot());
            return parts.Count == 0 ? "a dialog opened and closed while the command waited"
                : "a dialog opened and closed while the command waited: " + string.Join("; ", parts.ToArray());
        }

        // The one line every consumer sees, whoever produces it: the agent in a
        // dialog_blocked reply, the CLI when a command is refused, `cts dialog`
        // when it prints what is on screen.
        //
        //   blocked by a dialog [id 3f9a1c02]: CODESYS - Which login? - options:
        //   (*) Keep, ( ) Never - buttons: [OK]
        //
        // A modal on a modal is rare but happens; then each dialog keeps its own
        // part, so the ids and the options stay attributable.
        public static string BlockLine(IReadOnlyList<ModalWindow> dialogs)
        {
            if (dialogs == null || dialogs.Count == 0) return "blocked by a dialog";
            if (dialogs.Count == 1) return "blocked by a dialog " + dialogs[0].Snapshot();
            var parts = new List<string>();
            foreach (var window in dialogs) parts.Add(window.Snapshot());
            return "blocked by a dialog: " + string.Join("; ", parts.ToArray());
        }
    }
}
