using System;
using System.Windows.Forms;

namespace Cts.Agent
{
    // Keeps the IDE's mirror current while nobody works: every few seconds on
    // the UI thread it asks IdleRefresh, and when the project's objects moved
    // since the last time it runs `cts compare` through the quick window's
    // runner, in the project's sync folder.  A project without one is passed
    // over until its objects move again.
    internal sealed class MirrorRefresh
    {
        const int LookEveryMs = 5000;

        readonly Ide _ide;
        readonly ObjectJournal _journal;
        readonly ModalState _modal;
        readonly PipeServer _pipe;
        readonly QuickWidget _widget;
        readonly FileLog _log;
        readonly IdleRefresh _due = new IdleRefresh();
        Timer _timer;

        public MirrorRefresh(Ide ide, ObjectJournal journal, ModalState modal, PipeServer pipe, QuickWidget widget, FileLog log)
        {
            _ide = ide;
            _journal = journal;
            _modal = modal;
            _pipe = pipe;
            _widget = widget;
            _log = log;
        }

        // On the UI thread: the timer ticks on the thread that makes it.
        public void Start()
        {
            _timer = new Timer { Interval = LookEveryMs };
            _timer.Tick += (s, e) => Look();
            _timer.Start();
        }

        public void Stop()
        {
            _timer?.Dispose();
        }

        void Look()
        {
            try
            {
                var stamp = _journal.Stamp;
                if (!_due.Due(stamp, Win32.InputIdleMs(), _pipe.QuietMs, _modal.AnyOpen || _widget.Busy)) return;
                _due.Done(stamp);
                var status = _ide.ProjectStatus();
                var folder = status.TryGetValue("sync_folder", out var value) ? Convert.ToString(value) : "";
                if (folder.Length == 0) return;
                _log.Write("mirror: the project changed, refreshing while nobody works");
                _widget.Refresh(folder);
            }
            catch (Exception error) { _log.Write("mirror: " + error.Message); }
        }
    }
}
