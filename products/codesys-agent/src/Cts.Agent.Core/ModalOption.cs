// The choice a dialog offers: one radio button or check box, and whether it is
// selected.
//
// Win32 cannot tell the three kinds of control apart on a CODESYS dialog: every
// button, radio button and check box there is a WindowsForms10.BUTTON window
// with the same owner-draw style, and BM_GETCHECK answers 0 for all of them.
// The kind and the state therefore come from the control itself -- the
// agent resolves the real System.Windows.Forms object behind the handle -- and
// this type is what that read produces.  A kind that could not be read is not
// guessed: the control is reported as a button instead, which keeps it
// pressable (see ModalWindow.Buttons).
//
// Plain data with no IDE and no WinForms anywhere, so the fingerprint, the
// snapshot line and the answer matching are unit-tested on Linux.
using System.Collections.Generic;
using System.Text;

namespace Cts.Agent
{
    public static class ModalOptionKind
    {
        public const string Radio = "radio";
        public const string Check = "check";
    }

    public sealed class ModalOption
    {
        //: The caption as the dialog shows it, with the & mnemonic removed.
        public string Caption;

        //: ModalOptionKind.Radio or ModalOptionKind.Check.
        public string Kind = ModalOptionKind.Check;

        //: null when the agent could not read the state (the control is not a
        //: .NET control this process can resolve, or it refused to say).
        public bool? Checked;

        public ModalOption() { }

        public ModalOption(string caption, string kind, bool? isChecked)
        {
            Caption = caption;
            Kind = string.IsNullOrEmpty(kind) ? ModalOptionKind.Check : kind;
            Checked = isChecked;
        }

        public bool IsRadio { get { return Kind == ModalOptionKind.Radio; } }

        //: `(*)` / `( )` for a radio and `[x]` / `[ ]` for a check box -- the
        //: notation a person already reads on paper -- with `?` inside when the
        //: state could not be read.
        public string Mark()
        {
            if (IsRadio) return Checked.HasValue ? (Checked.Value ? "(*)" : "( )") : "(?)";
            return Checked.HasValue ? (Checked.Value ? "[x]" : "[ ]") : "[?]";
        }

        public Dictionary<string, object> ToData()
        {
            return new Dictionary<string, object>
            {
                { "caption", Caption ?? "" },
                { "kind", Kind },
                { "checked", Checked.HasValue ? (object)Checked.Value : null },
            };
        }
    }

    // What "the same caption" means, in one place.
    //
    // Win32 marks the accelerator letter with an & ("&OK", "Login with &online
    // change"); a client names the control without it, and is allowed to keep
    // it.  Case is not significant.  && is a literal ampersand and survives.
    public static class ModalCaption
    {
        //: The caption as it is shown: mnemonics removed, trimmed.
        public static string Display(string caption)
        {
            if (string.IsNullOrEmpty(caption)) return "";
            var sb = new StringBuilder(caption.Length);
            for (var i = 0; i < caption.Length; i++)
            {
                var c = caption[i];
                if (c != '&') { sb.Append(c); continue; }
                if (i + 1 < caption.Length && caption[i + 1] == '&')
                {
                    sb.Append('&');
                    i++;
                    continue;
                }
                // A lone & marks the next character; drop the & and keep it.
            }
            return sb.ToString().Trim();
        }

        //: The matching key: the display form, lowercased.
        public static string Key(string caption)
        {
            return Display(caption).ToLowerInvariant();
        }

        //: Exact match, case-insensitive, & ignored.
        public static bool Same(string a, string b)
        {
            return Key(a) == Key(b);
        }
    }

    // A short, stable fingerprint of a dialog: the same dialog says the same id
    // on every poll, and two different dialogs practically never share one.
    //
    // It is built from what a caller *read* (the title, the text, the captions
    // of the options and the buttons), never from the window handle -- a handle
    // changes with the process and says nothing about the question being asked.
    // The selected state is deliberately NOT part of it: which radio is
    // selected is the answer, not the identity, so a dialog the user has
    // partly filled in keeps its id.
    public static class ModalFingerprint
    {
        public static string Of(ModalWindow window)
        {
            if (window == null) return "";
            return Of(window.Title, window.Text, window.Options, window.Buttons);
        }

        public static string Of(string title, string text, IEnumerable<ModalOption> options, IEnumerable<string> buttons)
        {
            var sb = new StringBuilder();
            sb.Append(ModalCaption.Key(title)).Append('\u001f');
            sb.Append(ModalCaption.Key(text)).Append('\u001f');
            if (options != null)
            {
                foreach (var option in options)
                {
                    if (option == null) continue;
                    sb.Append(option.Kind).Append('\u001d').Append(ModalCaption.Key(option.Caption)).Append('\u001e');
                }
            }
            sb.Append('\u001f');
            if (buttons != null)
            {
                foreach (var button in buttons)
                {
                    if (button == null) continue;
                    sb.Append(ModalCaption.Key(button)).Append('\u001e');
                }
            }
            return Hash(sb.ToString());
        }

        // FNV-1a over the UTF-16 code units, 32 bits, eight hex digits.  Not a
        // security hash: it only has to be stable and wide enough that a
        // changed caption is not mistaken for the same dialog.
        static string Hash(string canonical)
        {
            unchecked
            {
                var hash = 2166136261u;
                foreach (var c in canonical)
                {
                    hash ^= (byte)(c & 0xff);
                    hash *= 16777619u;
                    hash ^= (byte)(c >> 8);
                    hash *= 16777619u;
                }
                return hash.ToString("x8");
            }
        }
    }
}
