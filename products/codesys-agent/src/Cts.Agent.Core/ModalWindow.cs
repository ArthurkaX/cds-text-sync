// One top-level window of the IDE process, as the Win32 side sees it, plus
// the choices it offers: the radio buttons and check boxes with their
// kind and selected state, and a short stable id for the dialog as a whole.
//
// Plain data: the net48 watcher fills it (Win32 for the window, the control
// itself for the options) and hands it to ModalState, which owns the ids.
// Nothing here touches the IDE, so the modal policy, the diff, the fingerprint
// and the wire shape are unit-tested on Linux.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using static Cts.Agent.JsonMap;

namespace Cts.Agent
{
    public sealed class ModalWindow
    {
        // Assigned by ModalState when the window is first seen and stable until
        // it closes; 0 before then.  It is the id the events and dialog.probe
        // carry, so a client can match "opened" with "closed".
        public long Id;

        public long Hwnd;
        public string Class;
        public string Title;

        // The dialog's own text: the first non-empty static/child caption, or
        // null when the dialog has none.
        public string Text;

        // The radio buttons and check boxes the dialog offers, in child order,
        // each with its kind and -- when the agent could read it -- whether it
        // is selected.  Empty when the dialog has none, and also when the
        // agent could not classify them: an unreadable control stays in Buttons
        // rather than being guessed at here.
        public ModalOption[] Options = new ModalOption[0];

        // The captions of the dialog's push buttons; empty when none.  A
        // button-class child the agent could not classify (no .NET control
        // behind the handle, so not a radio, a check box or a button for sure)
        // is listed here too: it keeps the control pressable by name instead of
        // dropping it.
        public string[] Buttons;

        public long Owner;
        public bool OwnerDisabled;
        public bool Ownerless;
        public bool Enabled;
        public bool Visible;

        string _fingerprint;

        // A short stable id for this dialog, from what it says (see
        // ModalFingerprint).  Recomputed once per window object.
        public string Fingerprint
        {
            get { return _fingerprint ?? (_fingerprint = ModalFingerprint.Of(this)); }
        }

        // The wire shape shared by dialog.probe, error.data and the ui.modal.*
        // events.  It is a superset of the event fields the design lists:
        // `enabled`, `visible` and `owner_disabled` are the policy inputs, so a
        // client can reproduce ModalPolicy.IsModal instead of trusting ours.
        public Dictionary<string, object> ToData()
        {
            var options = new List<object>();
            foreach (var option in Options ?? new ModalOption[0])
                if (option != null) options.Add(option.ToData());
            return new Dictionary<string, object>
            {
                { "id", Id },
                { "fingerprint", Fingerprint },
                { "hwnd", Hwnd },
                { "class", Class },
                { "title", Title },
                { "text", Text },
                { "options", options },
                { "buttons", Buttons ?? new string[0] },
                { "owner", Owner },
                { "ownerless", Ownerless },
                { "owner_disabled", OwnerDisabled },
                { "enabled", Enabled },
                { "visible", Visible },
            };
        }

        // A compact one-line description for an error message: the id, the
        // title, the text on one line, the options with their marks and
        // the buttons.  Never fails.
        //
        //   [id 3f9a1c02]: CODESYS - The application changed since last
        //   download. What do you want to do? - options: (*) Login with online
        //   change, ( ) Login with download - buttons: [OK] [Cancel]
        //
        // It is one line so a caller can print it as-is, and it leads with the
        // id so the same line doubles as the argument to `cts dialog answer
        // --id`.
        public string Snapshot()
        {
            var sb = new StringBuilder();
            sb.Append("[id ").Append(Fingerprint).Append("]: ");
            sb.Append(string.IsNullOrEmpty(Title) ? "(untitled dialog)" : ModalCaption.Display(Title));
            var text = OneLine(Text);
            if (!string.IsNullOrEmpty(text)) sb.Append(" - ").Append(text);
            if (Options != null && Options.Length > 0)
            {
                sb.Append(" - options: ");
                for (var i = 0; i < Options.Length; i++)
                {
                    if (i > 0) sb.Append(", ");
                    sb.Append(Options[i].Mark()).Append(' ').Append(ModalCaption.Display(Options[i].Caption));
                }
            }
            if (Buttons != null && Buttons.Length > 0)
            {
                sb.Append(" - buttons: [");
                for (var i = 0; i < Buttons.Length; i++)
                {
                    if (i > 0) sb.Append("] [");
                    sb.Append(ModalCaption.Display(Buttons[i]));
                }
                sb.Append(']');
            }
            return sb.ToString();
        }

        // A window from its wire shape (dialog.probe, a refusal's data), with
        // the fingerprint it was sent with: what the caller renders is what
        // `cts dialog answer --id` has to match.
        public static ModalWindow FromData(IDictionary<string, object> data)
        {
            var options = new List<ModalOption>();
            foreach (var item in Items(data, "options"))
                if (item is IDictionary<string, object> option)
                    options.Add(new ModalOption(Field(option, "caption"), Field(option, "kind"),
                        option.TryGetValue("checked", out var isChecked) && isChecked is bool b ? b : (bool?)null));
            return new ModalWindow
            {
                Title = Field(data, "title"),
                Text = Field(data, "text"),
                Options = options.ToArray(),
                Buttons = Items(data, "buttons").Select(b => System.Convert.ToString(b)).ToArray(),
                _fingerprint = Field(data, "fingerprint"),
            };
        }

        static string Field(IDictionary<string, object> data, string key)
        {
            return data.TryGetValue(key, out var value) ? value as string : null;
        }

        // Every line of the text: the question is often the last one ("Do you
        // want to assign the newest profile?"), after the explanation.
        static string OneLine(string text)
        {
            if (string.IsNullOrEmpty(text)) return null;
            var lines = text.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
                .Select(line => line.Trim()).Where(line => line.Length > 0);
            return string.Join(" ", lines);
        }
    }
}
