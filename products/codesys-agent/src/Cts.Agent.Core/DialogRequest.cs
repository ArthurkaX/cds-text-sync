// What `cts dialog answer` asked for, and how it is checked against the dialog
// that is actually on screen.
//
// The two halves are separate on purpose:
//
//   DialogRequest.Parse  reads the wire params (a missing `press` is refused);
//   DialogResolver.Resolve matches the names against one snapshot.
//
// Resolve never guesses and never applies a default: an option or a button the
// caller named must exist exactly once (case-insensitive, & ignored), and when
// `id` was given it must still be the dialog that was read.  A refusal throws
// the structured error the CLI prints, with the current dialog in
// error.data.dialogs, so the caller sees what it was looking at instead.
using System;
using System.Collections.Generic;

namespace Cts.Agent
{
    public sealed class DialogRequest
    {
        //: The fingerprint the caller read; null when it did not pass --id.
        public string Id;

        //: Option captions to select (a radio) or check (a check box).
        public string[] Choose = new string[0];

        //: Option captions to clear.  A radio cannot be cleared, and saying so
        //: is a refusal, not a silent no-op.
        public string[] Uncheck = new string[0];

        //: The button to press.  Required: an answer is a choice plus the button
        //: that submits it.
        public string Press;

        public static DialogRequest Parse(Request request)
        {
            var parsed = new DialogRequest();
            var id = request.String("id", "");
            if (!string.IsNullOrEmpty(id)) parsed.Id = id.Trim();
            parsed.Choose = Captions(request, "choose");
            parsed.Uncheck = Captions(request, "uncheck");
            parsed.Press = (request.String("press", "") ?? "").Trim();
            if (parsed.Press.Length == 0)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "'press' is required: name the button that answers the dialog, e.g. press=\"OK\"");
            return parsed;
        }

        // A list-of-strings parameter; a missing one is an empty list, and a
        // present-but-wrong one is bad_params (never coerced).
        static string[] Captions(Request request, string name)
        {
            object value;
            if (!request.Params.TryGetValue(name, out value) || value == null) return new string[0];
            var list = value as IEnumerable<object>;
            if (list == null)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "parameter '" + name + "' must be an array of strings");
            var captions = new List<string>();
            foreach (var item in list)
            {
                var text = item as string;
                if (text == null)
                    throw new ProtocolException(ErrorCodes.BadParams,
                        "parameter '" + name + "' must contain only strings");
                if (text.Trim().Length > 0) captions.Add(text.Trim());
            }
            return captions.ToArray();
        }
    }

    // What to do to a dialog, in terms of the captions the caller used.
    public sealed class DialogPlan
    {
        public string[] Choose = new string[0];
        public string[] Uncheck = new string[0];
        public string Press;
        public ModalWindow Dialog;
    }

    public static class DialogResolver
    {
        public static DialogPlan Resolve(ModalWindow dialog, DialogRequest request)
        {
            if (dialog == null)
                throw new ProtocolException(ErrorCodes.DialogChanged,
                    "that dialog is not open any more");

            // The id is checked against the *fresh* read, never against the
            // snapshot the caller saw: between its `cts dialog` and its answer
            // the dialog may have been replaced by another one with the same
            // buttons (CODESYS chains them, e.g. Clean All -> login).
            if (!string.IsNullOrEmpty(request.Id) && request.Id != dialog.Fingerprint)
                throw new ProtocolException(ErrorCodes.DialogChanged,
                    "the dialog changed since it was read: that was id " + request.Id
                    + ", the dialog on screen is id " + dialog.Fingerprint,
                    Dialogs(dialog));

            var plan = new DialogPlan { Dialog = dialog };
            plan.Choose = ResolveOptions(dialog, request.Choose, "choose");
            plan.Uncheck = ResolveUncheck(dialog, request.Uncheck);
            plan.Press = ResolveButton(dialog, request.Press);
            return plan;
        }

        static string[] ResolveOptions(ModalWindow dialog, string[] wanted, string parameter)
        {
            var found = new List<string>();
            foreach (var name in wanted)
                found.Add(Find(dialog.Options, dialog, name, parameter).Caption);
            return found.ToArray();
        }

        static string[] ResolveUncheck(ModalWindow dialog, string[] wanted)
        {
            var found = new List<string>();
            foreach (var name in wanted)
            {
                var option = Find(dialog.Options, dialog, name, "uncheck");
                if (option.IsRadio)
                    throw new ProtocolException(ErrorCodes.BadParams,
                        "'" + name + "' is a radio button; a radio cannot be cleared, choose another option",
                        Dialogs(dialog));
                found.Add(option.Caption);
            }
            return found.ToArray();
        }

        static string ResolveButton(ModalWindow dialog, string name)
        {
            var buttons = dialog.Buttons ?? new string[0];
            var matched = Match(buttons, name);
            if (matched.Count == 0)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "no button named '" + name + "'; the dialog has: " + Labels(buttons), Dialogs(dialog));
            if (matched.Count > 1)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "two buttons are named '" + name + "'; the dialog has: " + Labels(buttons), Dialogs(dialog));
            return matched[0];
        }

        static ModalOption Find(ModalOption[] options, ModalWindow dialog, string name, string parameter)
        {
            var list = options ?? new ModalOption[0];
            var matched = new List<ModalOption>();
            foreach (var option in list)
                if (ModalCaption.Same(option.Caption, name)) matched.Add(option);

            if (matched.Count == 1) return matched[0];

            var available = list.Length == 0
                ? "none that could be read"
                : string.Join(", ", Array.ConvertAll(list, o => ModalCaption.Display(o.Caption)));
            if (matched.Count > 1)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "two options are named '" + name + "'; the dialog has: " + available, Dialogs(dialog));
            throw new ProtocolException(ErrorCodes.BadParams,
                "no option named '" + name + "' to " + parameter + "; the dialog has: " + available,
                Dialogs(dialog));
        }

        static List<string> Match(string[] candidates, string name)
        {
            var matched = new List<string>();
            foreach (var candidate in candidates ?? new string[0])
                if (ModalCaption.Same(candidate, name)) matched.Add(candidate);
            return matched;
        }

        static string Labels(string[] captions)
        {
            if (captions == null || captions.Length == 0) return "(none)";
            var parts = new List<string>();
            foreach (var caption in captions) parts.Add("[" + ModalCaption.Display(caption) + "]");
            return string.Join(" ", parts.ToArray());
        }

        // The error detail every refusal carries: the dialog as it is right now,
        // so the caller can print it and try again without a second round trip.
        public static Dictionary<string, object> Dialogs(ModalWindow dialog)
        {
            var list = new List<object>();
            if (dialog != null) list.Add(dialog.ToData());
            return new Dictionary<string, object> { { "dialogs", list } };
        }
    }
}
