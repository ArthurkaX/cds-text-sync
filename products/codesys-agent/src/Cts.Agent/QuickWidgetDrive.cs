#if DEBUG
using System;
using System.Collections.Generic;
using System.Threading;
using System.Windows.Forms;

namespace Cts.Agent
{
    internal sealed partial class QuickWidget
    {
        // ---- widget.snapshot / widget.drive (Debug build only): the window
        // worked from the pipe as a person would, for tests of the window.
        // Each step runs on the UI thread through the handlers a key or a
        // click reaches; the pipe thread waits for it. A step that opens a
        // dialog (a question box, the folder dialog) does not come back while
        // it is up: the reply then says dialog=true and dialog.probe /
        // dialog.answer take over.

        const int IdlePollMs = 150;
        const int IdlePolls = 3;

        internal IDictionary<string, object> Snapshot()
        {
            var snapshot = OnUi(() => _form is WidgetView view ? view.Snapshot() : new Dictionary<string, object> { { "open", false } }, DateTime.UtcNow.AddSeconds(10));
            snapshot["comparing"] = _comparing > 0;
            snapshot["dialog"] = _modal.AnyOpen;
            return snapshot;
        }

        internal IDictionary<string, object> Drive(IEnumerable<object> raw, int timeoutMs)
        {
            var steps = WidgetDrive.Parse(raw);
            var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            string clipboard = null;
            foreach (var step in steps)
            {
                if (step.Kind == DriveKind.Wait) { Thread.Sleep(step.Milliseconds); continue; }
                if (step.Kind == DriveKind.Idle) { if (!WaitIdle(deadline)) break; continue; }
                if (!Act(step, deadline)) return Finished(false, null);
                // The window greys its rows while its first compare runs, as a person sees before pressing.
                if (step.Kind == DriveKind.Open && !WaitIdle(deadline)) break;
                if (step.Kind == DriveKind.Copy || step.Text == "ctrl+c") clipboard = OnUi(() => Clipboard.GetText(), deadline);
            }
            return Finished(WaitIdle(deadline), clipboard);
        }

        IDictionary<string, object> Finished(bool idle, string clipboard)
        {
            var snapshot = Snapshot();
            snapshot["idle"] = idle;
            if (clipboard != null) snapshot["clipboard"] = clipboard;
            return snapshot;
        }

        // One step on the UI thread; false when a dialog came up instead of its end.
        bool Act(DriveStep step, DateTime deadline)
        {
            var done = new ManualResetEventSlim();
            Exception failed = null;
            _ui.Post(_ =>
            {
                try { Do(step); }
                catch (Exception e) { failed = e; }
                finally { done.Set(); }
            }, null);
            while (!done.Wait(100))
            {
                if (_modal.AnyOpen) return false;
                if (DateTime.UtcNow > deadline) throw new TimeoutException("widget.drive: step " + step.Kind + " " + step.Text + " did not end in time");
            }
            if (failed != null) throw new InvalidOperationException(failed.Message, failed);
            return true;
        }

        void Do(DriveStep step)
        {
            if (step.Kind == DriveKind.Open) { if (_form == null) Open(); return; }
            var view = _form as WidgetView;
            if (step.Kind == DriveKind.Close) { view?.Close(); return; }
            if (view == null) throw new InvalidOperationException("the quick window is not open: start with the step open");
            switch (step.Kind)
            {
                case DriveKind.Char: view.Press(step.Text[0]); return;
                case DriveKind.Type: view.Type(step.Text); return;
                case DriveKind.Copy: view.ClickCopy(); return;
                case DriveKind.Key: view.Press(KeyOf(step.Text)); return;
            }
        }

        static Keys KeyOf(string name)
        {
            switch (name)
            {
                case "enter": return Keys.Enter;
                case "esc": return Keys.Escape;
                case "left": return Keys.Left;
                case "right": return Keys.Right;
                case "up": return Keys.Up;
                case "down": return Keys.Down;
                case "space": return Keys.Space;
                case "backspace": return Keys.Back;
                case "f4": return Keys.F4;
                case "pgup": return Keys.PageUp;
                case "pgdn": return Keys.PageDown;
                default: return Keys.Control | Keys.C;
            }
        }

        // Until no run or compare goes and the window shows the same for a
        // few polls (a page read off the UI thread arrives a moment later);
        // false at the deadline or when a dialog is up.
        bool WaitIdle(DateTime deadline)
        {
            string last = null;
            var same = 0;
            while (DateTime.UtcNow < deadline)
            {
                if (_modal.AnyOpen) return false;
                var snapshot = Snapshot();
                var now = Json.Serialize(snapshot);
                var quiet = !Equals(snapshot.ContainsKey("running") ? snapshot["running"] : null, true) && _comparing == 0;
                same = quiet && now == last ? same + 1 : 0;
                if (same >= IdlePolls) return true;
                last = now;
                Thread.Sleep(IdlePollMs);
            }
            return false;
        }

        T OnUi<T>(Func<T> read, DateTime deadline)
        {
            var done = new ManualResetEventSlim();
            var value = default(T);
            Exception failed = null;
            _ui.Post(_ =>
            {
                try { value = read(); }
                catch (Exception e) { failed = e; }
                finally { done.Set(); }
            }, null);
            if (!done.Wait(TimeSpan.FromMilliseconds(Math.Max(1000, (deadline - DateTime.UtcNow).TotalMilliseconds))))
                throw new TimeoutException("widget.drive: the IDE's UI thread did not answer");
            if (failed != null) throw new InvalidOperationException(failed.Message, failed);
            return value;
        }
    }
}
#endif
