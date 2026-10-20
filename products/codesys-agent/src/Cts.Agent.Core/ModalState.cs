// The agent's view of "which modal dialogs are open right now", plus the
// generation counter (Epoch) that lets a queued UI call notice a dialog that
// appeared -- or opened and closed -- while it was waiting.
//
// The watcher calls Update() with every top-level window of the UI thread.
// Only the modal ones (ModalPolicy) are tracked.  Update diffs by HWND, keeps a
// stable id per window, bumps Epoch once per opened and once per closed window,
// and raises Opened/Closed outside its lock.
using System;
using System.Collections.Generic;

namespace Cts.Agent
{
    // What one Update changed: the windows that appeared and the ones that went
    // away (with the id they had).  Returned so the caller can log or publish
    // without subscribing to the events.
    public sealed class ModalDiff
    {
        public ModalWindow[] Opened = new ModalWindow[0];
        public ModalWindow[] Closed = new ModalWindow[0];

        public bool Changed { get { return Opened.Length > 0 || Closed.Length > 0; } }
    }

    public sealed class ModalState
    {
        readonly object _lock = new object();
        readonly Dictionary<long, ModalWindow> _open = new Dictionary<long, ModalWindow>();
        // The last few windows that closed, each with the epoch its close made.
        readonly List<KeyValuePair<long, ModalWindow>> _closed = new List<KeyValuePair<long, ModalWindow>>();
        const int ClosedKept = 8;
        // The last few windows that opened, each with the epoch its opening made.
        readonly List<KeyValuePair<long, ModalWindow>> _opened = new List<KeyValuePair<long, ModalWindow>>();
        const int OpenedKept = 16;
        long _epoch;
        long _nextId;

        // Raised after the lock is released, once per window that appeared or
        // went away.  A handler must stay cheap and must not throw.
        public event Action<ModalWindow> Opened;
        public event Action<ModalWindow> Closed;

        // Bumped for every open and every close; a UI call that queued at Epoch
        // N and starts at Epoch M != N knows a dialog came or went meanwhile.
        public long Epoch { get { lock (_lock) { return _epoch; } } }

        public bool AnyOpen { get { lock (_lock) { return _open.Count > 0; } } }

        // The modal windows, newest first (by id): a dialog stacked on another
        // takes the input, so it is the one to answer first.  A copy: the
        // caller may hold it while a poll replaces the snapshot.
        public ModalWindow[] Current { get { lock (_lock) { return Snapshot(); } } }

        // The windows that closed after *epoch*, newest first: what a call that
        // queued at that epoch names when the dialog came and went meanwhile.
        public ModalWindow[] ClosedSince(long epoch)
        {
            lock (_lock)
            {
                var list = new List<ModalWindow>();
                for (var i = _closed.Count - 1; i >= 0; i--)
                    if (_closed[i].Key > epoch) list.Add(_closed[i].Value);
                return list.ToArray();
            }
        }

        // The windows that opened after *epoch*, oldest first, open or closed
        // since: what a call that began at that epoch names as seen meanwhile.
        public ModalWindow[] OpenedSince(long epoch)
        {
            lock (_lock)
            {
                var list = new List<ModalWindow>();
                foreach (var pair in _opened)
                    if (pair.Key > epoch) list.Add(pair.Value);
                return list.ToArray();
            }
        }

        // Reconciles the tracked set with one poll and returns the difference.
        public ModalDiff Update(IReadOnlyList<ModalWindow> windows)
        {
            var diff = new ModalDiff();
            var opened = new List<ModalWindow>();
            var closed = new List<ModalWindow>();
            lock (_lock)
            {
                var seen = new HashSet<long>();
                if (windows != null)
                {
                    foreach (var window in windows)
                    {
                        if (window == null || !ModalPolicy.IsModal(window)) continue;
                        seen.Add(window.Hwnd);

                        ModalWindow tracked;
                        if (_open.TryGetValue(window.Hwnd, out tracked))
                        {
                            // The same dialog, still open: refresh what it says
                            // (a progress dialog rewrites its text and buttons),
                            // keep its id and leave the epoch alone.
                            window.Id = tracked.Id;
                            _open[window.Hwnd] = window;
                            continue;
                        }

                        window.Id = ++_nextId;
                        _open.Add(window.Hwnd, window);
                        _epoch++;
                        opened.Add(window);
                        _opened.Add(new KeyValuePair<long, ModalWindow>(_epoch, window));
                        if (_opened.Count > OpenedKept) _opened.RemoveAt(0);
                    }
                }

                var gone = new List<long>();
                foreach (var pair in _open)
                    if (!seen.Contains(pair.Key)) gone.Add(pair.Key);
                foreach (var hwnd in gone)
                {
                    var window = _open[hwnd];
                    _open.Remove(hwnd);
                    _epoch++;
                    closed.Add(window);
                    _closed.Add(new KeyValuePair<long, ModalWindow>(_epoch, window));
                    if (_closed.Count > ClosedKept) _closed.RemoveAt(0);
                }
            }

            diff.Opened = opened.ToArray();
            diff.Closed = closed.ToArray();
            Raise(Closed, closed);
            Raise(Opened, opened);
            return diff;
        }

        void Raise(Action<ModalWindow> handler, List<ModalWindow> windows)
        {
            if (handler == null) return;
            foreach (var window in windows)
            {
                try { handler(window); } catch { }
            }
        }

        ModalWindow[] Snapshot()
        {
            var list = new List<ModalWindow>(_open.Values);
            list.Sort((a, b) => b.Id.CompareTo(a.Id));
            return list.ToArray();
        }
    }
}
