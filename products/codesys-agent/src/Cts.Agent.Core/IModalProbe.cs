// "Is a modal dialog open *right now*?" -- answered by a fresh look, not by the
// watcher's cached snapshot.
//
// The snapshot is a 500 ms poll, so right after a dialog closes it still names
// the dialog that just went away.  Before a refusal is based
// on it, the gate and the UiCall guard call this once: a ConfirmModal() that
// finds nothing means the snapshot was stale and the call may proceed.
//
// The implementation lives in Cts.Agent (the Win32 EnumThreadWindows poll) and
// must run on the *caller's* thread, never the UI thread.  It updates ModalState
// as a side effect, so the snapshot, the epoch and the ui.modal.* events agree
// with the answer it returns.
namespace Cts.Agent
{
    public interface IModalProbe
    {
        // Re-reads the UI thread's windows now and returns whether a modal is
        // open after the read.  Cheap and safe to call from any thread; never
        // throws into the caller's decision.
        bool ConfirmModal();
    }
}
