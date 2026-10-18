// The agent's IModalProbe: a fresh look at the IDE process's windows, taken on the
// *calling* thread (a pipe thread or the UI-thread's caller -- never the UI
// thread itself), reconciling ModalState so the snapshot, the epoch and the
// ui.modal.* events all agree with the answer.
//
// It is the confirm step behind the router gate and UiCall's epoch guard: before
// a refusal based on the cached 500 ms snapshot, the gate asks this once, and a
// "nothing open now" answer means the snapshot was stale and the call proceeds
//.
using System;

namespace Cts.Agent
{
    internal sealed class ModalProbe : IModalProbe
    {
        readonly ModalWatcher _watcher;
        readonly ModalState _state;
        readonly FileLog _log;

        public ModalProbe(ModalWatcher watcher, ModalState state, FileLog log)
        {
            if (watcher == null) throw new ArgumentNullException("watcher");
            if (state == null) throw new ArgumentNullException("state");
            _watcher = watcher;
            _state = state;
            _log = log;
        }

        public bool ConfirmModal()
        {
            try { _watcher.Refresh(); }
            catch (Exception e) { _log.Write("modal confirm failed: " + e.Message); }
            // Refresh reconciles ModalState; the snapshot is its answer.
            return _state.AnyOpen;
        }
    }
}
