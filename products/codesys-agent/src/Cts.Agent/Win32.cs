// The Win32 surface the agent needs: reading another window's state, posting
// a click to it, the quick widget's keyboard hook, and how long the person has been away.
//
// Reading never posts a message to the target -- GetWindowText would send
// WM_GETTEXT to the very thread the watcher is trying to diagnose, and that
// thread is inside a modal loop.  InternalGetWindowText and GetClassName read
// the window's own storage instead, so a poll is safe from any thread.
//
// Clicking is the one place a message is posted, and it is posted, not sent:
// the point of `cts dialog answer` is that the UI thread is inside a modal loop
// it is already pumping, so the click runs when that loop gets to it, and the
// caller verifies the result by watching the window close.
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace Cts.Agent
{
    internal static class Win32
    {
        public const uint GW_OWNER = 4;

        //: What a dialog receives when one of its buttons is clicked
        //: (BN_CLICKED is notification code 0, the high word of wparam).
        const uint WM_COMMAND = 0x0111;

        const uint WM_CLOSE = 0x0010;

        const int MaxText = 2048;

        public delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr param);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr param);

        [DllImport("user32.dll")]
        public static extern int GetWindowThreadProcessId(IntPtr hwnd, out int processId);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern bool EnumChildWindows(IntPtr parent, EnumWindowsProc callback, IntPtr param);

        [DllImport("user32.dll")]
        public static extern IntPtr GetWindow(IntPtr hwnd, uint command);

        [DllImport("user32.dll")]
        public static extern bool IsWindowEnabled(IntPtr hwnd);

        [DllImport("user32.dll")]
        public static extern bool IsWindowVisible(IntPtr hwnd);

        [DllImport("user32.dll")]
        public static extern bool IsWindow(IntPtr hwnd);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        static extern int GetClassName(IntPtr hwnd, StringBuilder text, int count);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        static extern int InternalGetWindowText(IntPtr hwnd, StringBuilder text, int count);

        [DllImport("user32.dll")]
        static extern bool PostMessage(IntPtr hwnd, uint message, IntPtr wparam, IntPtr lparam);

        // Posts WM_CLOSE: the window closes as by its close button.
        public static bool Close(IntPtr hwnd) => PostMessage(hwnd, WM_CLOSE, IntPtr.Zero, IntPtr.Zero);

        [DllImport("user32.dll")]
        static extern IntPtr GetParent(IntPtr hwnd);

        [DllImport("user32.dll")]
        static extern int GetDlgCtrlID(IntPtr hwnd);

        [DllImport("user32.dll")]
        public static extern IntPtr SendMessage(IntPtr hwnd, int message, IntPtr wparam, IntPtr lparam);

        //: A message whose lparam points at a POINT (a rich edit's scroll position).
        [DllImport("user32.dll")]
        public static extern IntPtr SendMessage(IntPtr hwnd, int message, IntPtr wparam, ref System.Drawing.Point lparam);

        [DllImport("kernel32.dll")]
        public static extern int GetCurrentThreadId();

        //: A keyboard hook's callback (the quick widget's key).
        public delegate IntPtr HookProc(int code, IntPtr wparam, IntPtr lparam);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern IntPtr SetWindowsHookEx(int kind, HookProc proc, IntPtr module, int threadId);

        [DllImport("user32.dll")]
        public static extern bool UnhookWindowsHookEx(IntPtr hook);

        //: Below zero while the key *vk* is down (VK_CONTROL 0x11, VK_SHIFT 0x10).
        [DllImport("user32.dll")]
        public static extern short GetKeyState(int vk);

        [StructLayout(LayoutKind.Sequential)]
        struct LastInput
        {
            public uint Size;
            public uint Tick;
        }

        [DllImport("user32.dll")]
        static extern bool GetLastInputInfo(ref LastInput info);

        // How long the person has not touched the keyboard or the mouse (0 when unknown).
        public static long InputIdleMs()
        {
            var info = new LastInput { Size = (uint)Marshal.SizeOf(typeof(LastInput)) };
            return GetLastInputInfo(ref info) ? unchecked((uint)Environment.TickCount - info.Tick) : 0;
        }

        [DllImport("user32.dll")]
        public static extern IntPtr CallNextHookEx(IntPtr hook, int code, IntPtr wparam, IntPtr lparam);

        public static string ClassName(IntPtr hwnd)
        {
            var text = new StringBuilder(MaxText);
            return GetClassName(hwnd, text, text.Capacity) > 0 ? text.ToString() : null;
        }

        public static string Text(IntPtr hwnd)
        {
            var text = new StringBuilder(MaxText);
            return InternalGetWindowText(hwnd, text, text.Capacity) > 0 ? text.ToString() : null;
        }

        //: Queues a button click to the window's thread.  Never blocks.  The
        //: dialog is told its button was clicked (WM_COMMAND, BN_CLICKED), as
        //: the button itself would tell it: BM_CLICK replays a mouse click,
        //: which an inactive dialog ignores -- a message box stacked on
        //: another dialog stayed open under it.
        public static bool Click(IntPtr hwnd)
        {
            var dialog = GetParent(hwnd);
            var id = GetDlgCtrlID(hwnd);
            return dialog != IntPtr.Zero && id != 0
                && PostMessage(dialog, WM_COMMAND, new IntPtr(id & 0xFFFF), hwnd);
        }

        //: Whether the window is still on screen: created *and* visible.  A
        //: dialog that closed either destroys its handle or hides it, and both
        //: mean the answer was taken.
        public static bool Showing(IntPtr hwnd)
        {
            return hwnd != IntPtr.Zero && IsWindow(hwnd) && IsWindowVisible(hwnd);
        }
    }
}
