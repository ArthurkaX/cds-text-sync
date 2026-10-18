using static Cts.Agent.Palette;

namespace Cts.Agent
{
    // The run in the footer: started, its stage, its verdict, the copied report and a busy IDE.
    internal sealed partial class WidgetView
    {
        // *what* runs ("cts compare"); *last*: what the last run of this kind
        // took, for the progress; null when unknown.
        public void Start(string what, long? last)
        {
            _ahead = null;
            Running = true;
            _last = last;
            _ok = null;
            _running = what;
            _footer = what;
            _footerColor = Ink;
            _clock.Restart();
            Relayout();
            _tick.Start();
        }

        // The stage the run reached, under what runs.
        public void Progress(string stage)
        {
            if (!Running) return;
            _footer = _running + "\n" + stage;
            Relayout();
        }

        public void Finish(bool ok, string line)
        {
            _ahead = null;
            Running = false;
            _copied = false;
            _ok = ok;
            _clock.Stop();
            _footer = line;
            _footerColor = ok ? Ink : Bad;
            Relayout();
        }

        // A compare of the folder started (*reason* WidgetMenu.Busy) or ended
        // (null): the rows that wait for it turn grey and back.
        // The report of the failure shown is on the clipboard: the link says so.
        public void Copied()
        {
            _copied = true;
            Invalidate(FooterRect());
        }

        // A row pressed while it waited said so in the footer: once the
        // compare ends that line is stale and the hint comes back.
        public void ShowBusy(string reason)
        {
            var was = _busy;
            _busy = reason;
            if (reason == null && was != null && _footer == was && !Running) { Idle(); return; }
            Invalidate();
        }
    }
}
