// Whether a top-level window means "the user is answering a dialog".
//
// The rule mirrors the TwinCAT-XAE-MCP watcher, which is the
// closest thing to a field-tested rule we have:
//
//   visible AND (the owner window is disabled
//                OR (it is a dialog class AND (ownerless OR disabled)))
//
// An owned, enabled #32770 is a modeless tool window (a palette, an inspector),
// not a modal.  The owner-disabled arm catches application-modal windows the
// vendor shows from native code with a class we do not know.
//
// Pure: the truth table is a unit test.
using System;

namespace Cts.Agent
{
    public static class ModalPolicy
    {
        //: The Win32 dialog class (a top-level dialog drawn by the dialog manager).
        public const string DialogClass = "#32770";

        public static bool IsModal(ModalWindow window)
        {
            if (window == null) return false;
            if (!window.Visible) return false;
            if (window.OwnerDisabled) return true;
            return window.Class == DialogClass && (window.Ownerless || !window.Enabled);
        }

        // Whether the window's children are worth walking for its text and
        // buttons: a real dialog, or any window that disabled its owner (CODESYS
        // draws its own message boxes with WinForms, not #32770).  The ownerless
        // main frame is never walked; its children are a whole forest.
        public static bool HasReadableChildren(ModalWindow window)
        {
            if (window == null) return false;
            return window.Class == DialogClass || window.OwnerDisabled;
        }

        // What a child control adds to the dialog's description.  Win32 dialogs
        // use the plain "Button" and "Static" classes; WinForms names its native
        // classes "WindowsForms10.BUTTON.app.…", and CODESYS's message boxes put
        // the message in a read-only "WindowsForms10.EDIT.app.…".
        public static ChildRole RoleOf(string className)
        {
            if (string.IsNullOrEmpty(className)) return ChildRole.Other;
            if (className == "Button") return ChildRole.Button;
            if (className == "Static") return ChildRole.Text;
            const string winForms = "WindowsForms10.";
            if (!className.StartsWith(winForms, StringComparison.Ordinal)) return ChildRole.Other;
            var kind = className.Substring(winForms.Length);
            if (kind.StartsWith("BUTTON.", StringComparison.Ordinal)) return ChildRole.Button;
            if (kind.StartsWith("EDIT.", StringComparison.Ordinal)
                || kind.StartsWith("STATIC.", StringComparison.Ordinal)) return ChildRole.Text;
            return ChildRole.Other;
        }
    }

    public enum ChildRole { Other, Button, Text }
}
