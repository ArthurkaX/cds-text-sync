// Reads one top-level window of the IDE's UI thread: what it says, what it
// offers, and -- for the answer path -- the live controls behind it.
//
// The reader exists twice over the same Win32 walk on purpose.  The watcher
// only needs ModalWindow (plain data, shareable with the Core, published in
// events).  `cts dialog answer` needs to *act* on the same controls it just
// read, so it takes the LiveDialog: the ModalWindow plus the Control objects,
// in the same order.  Both come from one walk, so a caption the caller was told
// about is a caption that can be clicked.
using System;
using System.Collections.Generic;

namespace Cts.Agent
{
    // One child control of a dialog: what it says and what it is.
    internal sealed class LiveControl
    {
        public long Hwnd;

        //: The caption as read (Win32 text, or the control's own Text).
        public string Raw;

        //: The caption as it is shown, with the & mnemonic removed.
        public string Caption;

        //: ModalOptionKind.Radio / .Check, or "button".
        public string Kind;

        //: null when the control has no readable checked state.
        public bool? Checked;

        //: The Windows Forms control, or null when the handle is not one this
        //: process can resolve (a Win32-drawn message box, say).
        public object Control;
    }

    internal sealed class LiveDialog
    {
        public ModalWindow Window;

        //: Every button-class child, in the order it was read; the options and
        //: the buttons of Window appear here in the same order.
        public List<LiveControl> Controls = new List<LiveControl>();

        //: The control whose caption matches, or null.  Matching is the same
        //: rule the resolver used, so a name it accepted is a name this finds.
        public LiveControl Find(string caption)
        {
            foreach (var control in Controls)
                if (ModalCaption.Same(control.Caption, caption)) return control;
            return null;
        }
    }

    internal static class WindowReader
    {
        //: The window as data -- what the watcher keeps.
        public static ModalWindow Read(IntPtr hwnd)
        {
            return ReadLive(hwnd).Window;
        }

        //: The window and the controls behind it -- what the answer path acts on.
        public static LiveDialog ReadLive(IntPtr hwnd)
        {
            var window = new ModalWindow { Hwnd = hwnd.ToInt64() };

            var owner = Win32.GetWindow(hwnd, Win32.GW_OWNER);
            window.Owner = owner.ToInt64();
            window.Ownerless = owner == IntPtr.Zero;
            window.OwnerDisabled = !window.Ownerless && !Win32.IsWindowEnabled(owner);
            window.Enabled = Win32.IsWindowEnabled(hwnd);
            window.Visible = Win32.IsWindowVisible(hwnd);
            window.Class = Win32.ClassName(hwnd);
            window.Title = Win32.Text(hwnd);
            window.Buttons = new string[0];

            var live = new LiveDialog { Window = window };
            if (ModalPolicy.HasReadableChildren(window)) ReadChildren(hwnd, live);
            return live;
        }

        //: Whether the window is still on screen, by handle alone.  Cheap: the
        //: answer path polls it while it waits for a pressed dialog to go away.
        public static bool Showing(long hwnd)
        {
            return Win32.Showing(new IntPtr(hwnd));
        }

        // The dialog's body text (its first non-empty text child), its options
        // and its buttons, in enumeration order.
        static void ReadChildren(IntPtr hwnd, LiveDialog live)
        {
            string text = null;
            var options = new List<ModalOption>();
            var buttons = new List<string>();

            var callback = new Win32.EnumWindowsProc((child, param) =>
            {
                // An exception must never escape into the enumerating thread.
                try
                {
                    var role = ModalPolicy.RoleOf(Win32.ClassName(child));
                    if (role == ChildRole.Button)
                    {
                        var raw = Win32.Text(child);
                        var control = ControlReader.Resolve(child.ToInt64());
                        var kind = control == null ? "button" : ControlReader.Kind(control);
                        var caption = control == null ? raw : ControlReader.Caption(control, raw);
                        if (string.IsNullOrEmpty(caption)) return true;

                        bool? isChecked = control == null ? (bool?)null : ControlReader.Checked(control);
                        live.Controls.Add(new LiveControl
                        {
                            Hwnd = child.ToInt64(),
                            Raw = caption,
                            Caption = ModalCaption.Display(caption),
                            Kind = kind,
                            Checked = isChecked,
                            Control = control,
                        });
                        if (kind == "button") buttons.Add(caption);
                        else options.Add(new ModalOption(caption, kind, isChecked));
                    }
                    else if (text == null && role == ChildRole.Text)
                    {
                        var caption = Win32.Text(child);
                        if (!string.IsNullOrEmpty(caption)) text = caption;
                    }
                }
                catch { }
                return true;
            });
            Win32.EnumChildWindows(hwnd, callback, IntPtr.Zero);

            live.Window.Text = text;
            live.Window.Options = options.ToArray();
            live.Window.Buttons = buttons.ToArray();
        }
    }
}
