using System.Collections.Generic;

namespace Cts.Cli
{
    internal static partial class ImportCommand
    {
        // One import keeps the planned work separate from its IDE and disk writes.
        sealed class ImportRun
        {
            readonly CliCall _call;
            readonly bool _syncing, _settling;

            // *settling*: after `cts export --tool`, only the text objects both
            // sides changed, the IDE's side carried, and the XML objects whose
            // edits merge; a sync of those alone.
            internal ImportRun(CliCall call, bool syncing, bool settling)
            {
                _call = call;
                _syncing = syncing;
                _settling = settling;
            }

            internal IDictionary<string, object> Execute()
            {
                var planner = new ImportPlanner(_call, _syncing, _settling, Plan(_call));
                var stop = planner.Plan(out var work);
                if (stop != null) return stop;
                if (_call.Options.Params.ContainsKey("dry_run")) return planner.DryRunAnswer();
                var apply = new ImportApply(_call, work);
                stop = apply.Preserve();
                if (stop != null) return stop;
                planner.MatchRenames();
                apply.ApplyTexts();
                apply.ApplyNatives();
                apply.ApplyTextLists();
                return apply.Finish();
            }
        }

    }
}
