using System;
using System.Threading;

namespace Cts.Agent
{
    // Runs a function on the IDE's UI thread from a pipe thread, with a deadline.
    //
    // `post` hands an action to the UI thread without blocking (the IDE side wraps
    // IEngine.InvokeInPrimaryThread in asynchronous mode).  There are three
    // outcomes and they mean different things:
    //
    //   busy           the UI thread did not *start* the call in time.  It never
    //                  ran and it is marked abandoned: when the UI thread finally
    //                  reaches it, it does nothing.  A command the caller gave up
    //                  on must never run late.
    //   dialog_blocked a modal dialog is open -- now, or it came and went while
    //                  this call was queued.  The action is NOT run: it would run
    //                  nested inside the dialog's modal loop.
    //   timeout        the UI thread started the call but it did not finish within
    //                  the (long) finish budget.  It cannot be cancelled, so the
    //                  outcome is genuinely UNKNOWN -- it may still complete.
    //
    // The caller matches on Code; the messages are frozen so the same failure
    // reads the same in every log.
    public static class UiCall
    {
        //: Frozen tails of the error messages (asserted by tests).
        public const string NotStarted = "was not started; nothing ran";
        public const string OutcomeUnknown = "its outcome is unknown (it may still complete)";

        public static T Run<T>(Action<Action> post, Func<T> fn, int timeoutMs, string what)
        {
            return Run(post, fn, timeoutMs, what, null, StartTimeout.FinishBackstopMs, null);
        }

        // `modal` is the agent's modal snapshot (null when there is none, e.g.
        // the dev tools); `finishTimeoutMs` bounds the wait *after* the call has
        // started -- a backstop against a UI thread wedged forever inside a
        // modal loop, not the start deadline the caller asked for.
        public static T Run<T>(Action<Action> post, Func<T> fn, int timeoutMs, string what,
            ModalState modal, int finishTimeoutMs)
        {
            return Run(post, fn, timeoutMs, what, modal, finishTimeoutMs, null);
        }

        // `probe` is the live confirm step (see IModalProbe).  When the cached
        // snapshot says a dialog is open, or the queued epoch moved, the guard
        // asks it for one fresh look before refusing; null means "no live look
        // available" and the cached snapshot is trusted instead.
        public static T Run<T>(Action<Action> post, Func<T> fn, int timeoutMs, string what,
            ModalState modal, int finishTimeoutMs, IModalProbe probe)
        {
            if (post == null) throw new ArgumentNullException("post");
            if (fn == null) throw new ArgumentNullException("fn");

            var done = new ManualResetEventSlim(false);
            var gate = new object();
            var started = false;
            var abandoned = false;
            T result = default(T);
            Exception error = null;

            // The modal generation at the moment the call was queued.  If it
            // differs when the action finally starts, a dialog opened or closed
            // in between and the world this call assumed is gone.
            var queuedEpoch = modal != null ? modal.Epoch : 0L;

            post(() =>
            {
                lock (gate)
                {
                    if (abandoned) return;
                    started = true;
                }
                if (modal != null)
                {
                    // Two reasons to hold a call: the cached snapshot says a
                    // dialog is open, or the epoch moved while the call waited
                    // (a dialog came, or came and went).  Either way, take one
                    // fresh look first -- on this thread, never the UI thread --
                    // so a refusal is never based on a snapshot the watcher has
                    // not caught up with.
                    var movedWhileQueued = modal.Epoch != queuedEpoch;
                    var open = modal.AnyOpen;
                    if (open || movedWhileQueued)
                    {
                        if (probe != null) open = probe.ConfirmModal();
                        if (open || movedWhileQueued)
                        {
                            // Do not run the action: it would execute inside the
                            // dialog's modal loop, on the UI thread, where a
                            // mutating command is the last thing we want.
                            error = open ? ModalErrors.Blocked(modal.Current) : ModalErrors.CameAndWent(modal.ClosedSince(queuedEpoch));
                            done.Set();
                            return;
                        }
                    }
                }
                try { result = fn(); }
                catch (Exception e) { error = e; }
                finally { done.Set(); }
            });

            if (!done.Wait(timeoutMs))
            {
                bool running;
                lock (gate)
                {
                    running = started;
                    if (!started) abandoned = true;
                }
                if (!running)
                    throw new ProtocolException(ErrorCodes.Busy,
                        "the IDE did not run '" + what + "' within " + timeoutMs + " ms (UI thread busy); it "
                        + NotStarted);
                if (!done.Wait(finishTimeoutMs))
                    throw new ProtocolException(ErrorCodes.Timeout,
                        "the IDE started '" + what + "' but it did not finish within " + finishTimeoutMs
                        + " ms; " + OutcomeUnknown);
            }

            if (error != null)
            {
                var pe = error as ProtocolException;
                if (pe != null) throw new ProtocolException(pe.Code, pe.Message, pe.Details);
                throw new InvalidOperationException(what + " failed on the UI thread: " + error.Message, error);
            }
            return result;
        }
    }
}
