// What a dialog's control *is*, from inside the process that owns it.
//
// Win32 cannot answer that question on a CODESYS dialog: every button, radio
// button and check box is a WindowsForms10.BUTTON window with the same
// owner-draw style, and BM_GETCHECK answers 0 for all of them (measured
// live).  The controls are Windows Forms, so the real object is one lookup
// away -- Control.FromHandle -- and that object knows its own kind and whether
// it is selected.
//
// FromHandle is a lookup in the process-wide handle table, not a call into the
// UI thread, so it is safe (and cheap) from the watcher's own thread.  It
// returns null when the handle belongs to a window this process did not create
// as a Control -- a message box drawn by the Win32 dialog manager, say -- and
// then the agent says "unknown" instead of guessing: the control stays a button
// and only --press is offered for it.
//
// Nothing here is a vendor type: System.Windows.Forms is the framework's own.
using System;
using System.Windows.Forms;

namespace Cts.Agent
{
    internal static class ControlReader
    {
        //: The control behind a window handle, or null when there is none.
        public static Control Resolve(long hwnd)
        {
            if (hwnd == 0) return null;
            try { return Control.FromHandle(new IntPtr(hwnd)); }
            catch (Exception) { return null; }
        }

        //: "radio", "check" or "button".  A control we cannot resolve is a
        //: button as far as this is concerned: that is what Win32 calls it, and
        //: it keeps the caption pressable.
        public static string Kind(Control control)
        {
            if (control is RadioButton) return ModalOptionKind.Radio;
            if (control is CheckBox) return ModalOptionKind.Check;
            return "button";
        }

        //: The control's own caption, which is what the user reads.  Preferred
        //: over the Win32 text, because it is the value the control renders.
        public static string Caption(Control control, string fallback)
        {
            try
            {
                var text = control.Text;
                if (!string.IsNullOrEmpty(text)) return text;
            }
            catch (Exception) { }
            return fallback;
        }

        //: Whether the control is selected, or null when it has no such state
        //: (or is a three-state box sitting in its indeterminate state, which is
        //: neither checked nor unchecked and must not be reported as either).
        public static bool? Checked(Control control)
        {
            try
            {
                var radio = control as RadioButton;
                if (radio != null) return radio.Checked;
                var check = control as CheckBox;
                if (check == null) return null;
                switch (check.CheckState)
                {
                    case CheckState.Checked: return true;
                    case CheckState.Unchecked: return false;
                    default: return null;
                }
            }
            catch (Exception) { return null; }
        }

        //: Select a radio or set a check box.  Runs on the UI thread, inside the
        //: dialog's own modal loop, which is what makes it legal: a radio goes
        //: through PerformClick so the group is handled the way a user's click
        //: handles it, a check box is set outright so its state is exactly what
        //: was asked for.
        public static bool SetState(Control control, bool value)
        {
            var radio = control as RadioButton;
            if (radio != null)
            {
                if (radio.Checked == value) return true;
                if (!value) return false;   // a radio is cleared by choosing another
                radio.PerformClick();
                return true;
            }
            var check = control as CheckBox;
            if (check == null) return false;
            if (check.CheckState != CheckState.Indeterminate
                && (check.CheckState == CheckState.Checked) == value) return true;
            check.Checked = value;
            return true;
        }

        //: Queue the control's own click to the UI thread.  Queued, not called:
        //: PerformClick runs the dialog's handler synchronously, and a handler
        //: that opens the *next* dialog (Clean All -> login) would otherwise
        //: block this call inside that dialog's modal loop.  The caller watches
        //: the window close instead of waiting here.
        public static bool PostClick(Control control)
        {
            var click = ClickAction(control);
            if (click == null) return false;
            control.BeginInvoke(click);
            return true;
        }

        // PerformClick is declared by Button and RadioButton and by no common
        // base (ButtonBase does not have it, and CheckBox has none at all), so
        // the control's own type decides how to ask for a click.  A control
        // with no such method is left to the caller's Win32 fallback.
        //
        // The interface they all implement (IButtonControl) is deliberately NOT
        // used: casting to it fails at runtime on the live IDE -- "Unable to
        // cast object of type 'System.Windows.Forms.RadioButton' to type
        // 'System.Windows.Forms.IButtonControl'" -- although the reference
        // assembly says the class implements it.  The class cast works, and the
        // method reached that way is the one the framework itself calls.
        static Action ClickAction(Control control)
        {
            var radio = control as RadioButton;
            if (radio != null) return () => radio.PerformClick();
            var button = control as Button;
            if (button != null) return () => button.PerformClick();
            return null;
        }

        //: How this control would be clicked, for the agent's log: the runtime
        //: type, and whether it really implements IButtonControl.
        public static string Describe(Control control)
        {
            if (control == null) return "no control";
            var type = control.GetType();
            var viaInterface = typeof(IButtonControl).IsAssignableFrom(type);
            return type.FullName + " (IButtonControl=" + viaInterface
                + ", clickable=" + (ClickAction(control) != null) + ")";
        }
    }
}
