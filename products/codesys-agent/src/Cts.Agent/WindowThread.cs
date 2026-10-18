// Back to a window's thread from a cts run or a log line: the action runs
// there later, or not at all when the window has closed meanwhile.
using System;
using System.Windows.Forms;

namespace Cts.Agent
{
    internal static class WindowThread
    {
        internal static void Later(Control window, Action action)
        {
            try { if (window.IsHandleCreated && !window.IsDisposed) window.BeginInvoke(action); }
            catch (InvalidOperationException) { }   // the handle went between the check and the call
        }
    }
}
