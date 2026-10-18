// ModalWatcher — a background poll of the IDE UI thread's top-level windows.
//
// Every PollMs it enumerates the IDE process's top-level windows (EnumWindows,
// every thread: CODESYS shows some errors from the thread that failed, e.g. a
// download's "Thread was being aborted" box, which disables the main window
// all the same), reads what they say (WindowReader), and hands them to
// ModalState.  ModalPolicy decides which of them mean "the user is answering a
// dialog"; a window that appears or disappears becomes a ui.modal.opened /
// ui.modal.closed event, and ModalState.Epoch -- which a queued UI call
// remembers -- moves on.
//
// Every call here only *reads* another window's state through the Win32 API:
// nothing is posted to the UI thread, so the watcher keeps working exactly when
// the UI thread is stuck inside a modal loop, which is the whole point.  Text is read with InternalGetWindowText, never
// GetWindowText: the latter sends WM_GETTEXT to the target and is documented to
// hang when the target does not pump messages -- and the target is the thread
// we are trying to diagnose.
//
// The watcher never throws into the IDE: a failing poll is logged and the next
// one tries again.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;

namespace Cts.Agent
{
    internal sealed class ModalWatcher
    {
        //: How often the windows are enumerated.  500 ms matches the order of
        //: the XAE watcher and is far below a human's reaction time.
        public const int PollMs = 500;

        readonly ModalState _state;
        readonly EventBus _bus;
        readonly FileLog _log;
        readonly Thread _thread;
        //: One lock around every poll (the watcher's own and a caller's confirm),
        //: so two of them can never interleave an enumerate with an Update and
        //: report a dialog that came and went as one that is still open.
        readonly object _pollLock = new object();
        readonly Stopwatch _clock = new Stopwatch();
        volatile bool _stop;
        readonly int _processId = Process.GetCurrentProcess().Id;
        volatile int _uiThreadId;
        long _polls;
        double _lastPollMs;

        public ModalWatcher(ModalState state, EventBus bus, FileLog log)
        {
            _state = state;
            _bus = bus;
            _log = log;
            _thread = new Thread(Loop) { IsBackground = true, Name = "cts-agent-modal" };
        }

        //: How many polls have run, and how long the last one took.  For measuring the confirm step live (`cts dialog --json`).
        public long Polls { get { return Interlocked.Read(ref _polls); } }

        public double LastPollMs { get { return _lastPollMs; } }

        public void Start()
        {
            // Start runs on the UI thread (the IDE executes the loader script
            // there), so its own id is the UI thread's.  Reading it directly
            // avoids posting to the UI thread -- a post could not run until Start
            // returned, so the old probe timed out after 5 s (t-a1).
            _uiThreadId = Win32.GetCurrentThreadId();
            _state.Opened += OnOpened;
            _state.Closed += OnClosed;
            _thread.Start();
            _log.Write("modal watcher started (process " + _processId + ", ui thread " + _uiThreadId
                + ", poll " + PollMs + " ms)");
        }

        //: Whether the window belongs to the IDE's UI thread; a dialog another
        //: thread shows runs its own modal loop there, not on the UI thread.
        public bool OnUiThread(long hwnd)
        {
            return Win32.GetWindowThreadProcessId(new IntPtr(hwnd), out _) == _uiThreadId;
        }

        // Enumerates the process's windows *now* and reconciles ModalState.
        // Safe to call from any thread: polls are serialized by one lock, and it
        // only reads other windows through Win32 (never posts to the UI thread),
        // so it stays cheap and keeps working while the UI thread is stuck.
        public void Refresh()
        {
            lock (_pollLock)
            {
                _clock.Restart();
                var windows = new List<ModalWindow>();
                var callback = new Win32.EnumWindowsProc((hwnd, param) =>
                {
                    // An exception must never escape into the enumerating thread.
                    try
                    {
                        int process;
                        Win32.GetWindowThreadProcessId(hwnd, out process);
                        if (process != _processId) return true;
                        var window = WindowReader.Read(hwnd);
                        if (window != null) windows.Add(window);
                    }
                    catch { }
                    return true;
                });
                Win32.EnumWindows(callback, IntPtr.Zero);
                // Only the modal windows are tracked; ModalState raises Opened/Closed.
                _state.Update(windows);
                _clock.Stop();
                _lastPollMs = _clock.Elapsed.TotalMilliseconds;
                Interlocked.Increment(ref _polls);
            }
        }

        public void Stop()
        {
            _stop = true;
            _state.Opened -= OnOpened;
            _state.Closed -= OnClosed;
            try { _thread.Join(2000); }
            catch (Exception e) { _log.Write("modal watcher did not stop: " + e.Message); }
        }

        void Loop()
        {
            while (!_stop)
            {
                try { Refresh(); }
                catch (Exception e) { _log.Write("modal poll failed: " + e.Message); }
                // Sleep in slices so Stop does not wait a whole period.
                for (var waited = 0; waited < PollMs && !_stop; waited += 50) Thread.Sleep(50);
            }
        }

        // Called from ModalState, after its lock is released.
        void OnOpened(ModalWindow window) { Publish("ui.modal.opened", window); }

        void OnClosed(ModalWindow window) { Publish("ui.modal.closed", window); }

        void Publish(string name, ModalWindow window)
        {
            try
            {
                var data = window.ToData();
                data["at"] = DateTime.UtcNow;
                _bus.Publish(name, data);
            }
            catch (Exception e)
            {
                _log.Write(name + " publish failed: " + e.Message);
            }
        }
    }
}
