using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Cts.Agent;

namespace Cts.Cli
{
    // A dialog that opens while an agent call runs. The call runs on the IDE's
    // UI thread and does not return while a dialog waits for an answer; the
    // agent answers dialog.probe off that thread, on a connection of its own,
    // so the CLI asks once a second and gives up the wait when a question has
    // stayed on screen for two seconds. A progress window (a lone Cancel, or
    // nothing to press) is part of the command, and so is a window that
    // flashes past: neither ends the wait.
    static class DialogWatch
    {
        const int PollMs = 1000;
        const int GraceMs = 2000;

        // The reply of *call*, or AgentException dialog_opened with the
        // dialogs in its data when a question stayed. *probe* lists the
        // dialogs on screen, empty when it could not tell.
        internal static object Await(Task<object> call, Func<IReadOnlyList<ModalWindow>> probe, string method)
        {
            var seen = new Dictionary<string, DateTime>(StringComparer.Ordinal);
            while (!((IAsyncResult)call).AsyncWaitHandle.WaitOne(PollMs))
            {
                var questions = probe().Where(IsQuestion).ToList();
                var now = DateTime.UtcNow;
                var shown = new HashSet<string>(questions.Select(window => window.Fingerprint), StringComparer.Ordinal);
                foreach (var gone in seen.Keys.Where(key => !shown.Contains(key)).ToList()) seen.Remove(gone);
                foreach (var window in questions)
                    if (!seen.ContainsKey(window.Fingerprint)) seen[window.Fingerprint] = now;
                var stayed = questions.Where(window => (now - seen[window.Fingerprint]).TotalMilliseconds >= GraceMs).ToList();
                if (stayed.Count == 0) continue;
                var detail = new Dictionary<string, object> { ["dialogs"] = stayed.Select(window => (object)window.ToData()).ToList() };
                throw new AgentException("dialog_opened", method + " is still running inside the IDE; it goes on once the dialog is answered, "
                    + "but this command does not wait for its reply: answer the dialog, then check with cts status before running it again", detail);
            }
            return call.GetAwaiter().GetResult();
        }

        // A question offers options, more than one button, or one button
        // that is not Cancel; a lone Cancel offers to abort a running job.
        internal static bool IsQuestion(ModalWindow window)
        {
            if (window.Options != null && window.Options.Length > 0) return true;
            var buttons = (window.Buttons ?? new string[0]).Where(caption => !string.IsNullOrEmpty(caption)).ToList();
            if (buttons.Count > 1) return true;
            return buttons.Count == 1 && ModalCaption.Key(buttons[0]) != "cancel";
        }

        // The `cts dialog answer` line for *window*, from its own captions:
        // the radio option already chosen and the first button, the IDE's
        // default. A check box keeps its state, so it is not named.
        internal static string AnswerLine(ModalWindow window)
        {
            var line = "cts dialog answer --id " + window.Fingerprint;
            var radios = (window.Options ?? new ModalOption[0]).Where(option => option.Kind == ModalOptionKind.Radio).ToList();
            if (radios.Count > 0)
            {
                var chosen = radios.FirstOrDefault(option => option.Checked == true) ?? radios[0];
                line += " --choose \"" + ModalCaption.Display(chosen.Caption) + "\"";
            }
            var button = (window.Buttons ?? new string[0]).FirstOrDefault(caption => !string.IsNullOrEmpty(caption));
            if (button != null) line += " --press \"" + ModalCaption.Display(button) + "\"";
            return line;
        }
    }
}
