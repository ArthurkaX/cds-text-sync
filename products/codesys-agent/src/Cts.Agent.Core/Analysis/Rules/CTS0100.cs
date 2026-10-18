using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // A program, function block, function or GVL nothing a task runs
    // reaches: no task calls it, no XML file (a system event, a screen)
    // names it, and no code reached from those names it. CODESYS builds only
    // what is reached, so it never gets to the PLC. Silent when the view
    // holds no task configuration.
    internal sealed class CTS0100 : Rule
    {
        static readonly Regex LinkAlways = new Regex(@"\{\s*attribute\s+'linkalways'\s*\}", RegexOptions.IgnoreCase);
        static readonly HashSet<string> Reported = new HashSet<string> { Analysis.Kinds.Program, Analysis.Kinds.FunctionBlock, Analysis.Kinds.Function, Analysis.Kinds.Gvl, Analysis.Kinds.GvlPersistent };

        internal CTS0100() : base("CTS0100", "Object not reached from a task", Analysis.Severity.Suspicious, "Correctness", "Programs, function blocks, functions and GVLs no task reaches are not built into the application.", "ANY")
        {
            Requires = new[] { Needs.Declarations, Needs.VisuXml };
        }

        internal override bool PerUnit => false;

        internal override IEnumerable<Finding> Check(RuleContext context)
        {
            if (!context.External.HasTasks) yield break;
            var units = context.Snapshot.Units;
            // What a name in code can mean: an object by its name, a GVL by a member.
            var byName = new Dictionary<string, List<Unit>>(StringComparer.OrdinalIgnoreCase);
            void Name(string name, Unit unit)
            {
                if (!byName.TryGetValue(name, out var list)) byName[name] = list = new List<Unit>();
                list.Add(unit);
            }
            foreach (var unit in units)
            {
                Name(Snapshot.LastSegment(unit.QualifiedName), unit);
                // A file named apart from a same-named one ("BACKGROUND__c40c81f7") keeps its declared name.
                if (unit.Header.Success) Name(unit.Header.Groups["name"].Value, unit);
                if (Analysis.Kinds.IsGlobals(unit.Kind)) foreach (var member in unit.Members().Where(member => member.Name.Length > 0)) Name(member.Name, unit);
            }
            var owned = units.Where(unit => unit.OwnerName != null).ToLookup(unit => unit.OwnerName.Split('.')[0], StringComparer.OrdinalIgnoreCase);
            var reached = new HashSet<Unit>();
            var queue = new Queue<Unit>();
            void Reach(Unit unit)
            {
                if (reached.Add(unit)) queue.Enqueue(unit);
            }
            foreach (var name in byName.Where(name => context.External.Names(name.Key))) foreach (var unit in name.Value) Reach(unit);
            foreach (var unit in units.Where(unit => unit.LinkAlways || LinkAlways.IsMatch(unit.Declaration ?? unit.Text ?? ""))) Reach(unit);
            while (queue.Count > 0)
            {
                var unit = queue.Dequeue();
                // A function block brings its methods, actions and properties.
                if (unit.OwnerName == null) foreach (var member in owned[unit.QualifiedName]) Reach(member);
                foreach (Match name in StText.Name.Matches(StText.Blanked(unit.Text ?? "")))
                    if (byName.TryGetValue(name.Value, out var meant)) foreach (var target in meant) Reach(target);
            }
            foreach (var unit in context.Units.Where(unit => Reported.Contains(unit.Kind) && !reached.Contains(unit)))
            {
                var header = unit.Header;
                var kind = header.Success ? header.Groups["kind"].Value.ToUpperInvariant() : "GVL";
                var name = header.Success ? header.Groups["name"].Value : Snapshot.LastSegment(unit.QualifiedName);
                int? offset = header.Success ? unit.DeclarationStart + header.Groups["name"].Index : (int?)null;
                yield return Finding.In(unit, kind + " '" + name + "' is not reached from any task, event or screen; CODESYS leaves it out of the application",
                    offset, offset + name.Length, name, kind);
            }
        }
    }
}
