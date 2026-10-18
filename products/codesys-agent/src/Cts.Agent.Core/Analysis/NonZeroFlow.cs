using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis
{
    // What the text of a unit's body before a use proves about a name being
    // non-zero (a divisor) or non-null (a pointer): the IFs around the use
    // (see Guards), an early exit, or the name's last assignment on the path
    // giving a value that is never zero. An IF without ELSE closed before the
    // use that sets a non-zero value when the name would be zero counts too
    // ("IF x < MIN_ITER THEN x := MIN_ITER; END_IF").
    internal sealed class NonZeroFlow
    {
        const int Deepest = 16;
        static readonly Regex Name = new Regex(@"^[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*$");
        static readonly Regex Function = new Regex(@"^(?<function>[A-Za-z_]\w*)\s*\((?<arguments>[^()]*)\)$");
        internal static readonly Regex Conversion = new Regex(@"^[A-Za-z]+_TO_[A-Za-z]+$", RegexOptions.IgnoreCase);
        static readonly Regex Address = new Regex(@"^ADR\s*\(", RegexOptions.IgnoreCase);
        static readonly Regex Offset = new Regex(@"^(?<name>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)\s*[+-]");
        static readonly Regex Referenced = new Regex(@"(?:\bADR\s*\(|REF=)\s*(?<name>[A-Za-z_]\w*)", RegexOptions.IgnoreCase);
        static readonly HashSet<string> Locals = new HashSet<string> { "VAR", "VAR_TEMP", "VAR_STAT" };
        static readonly Regex Comparison = new Regex(@"^\(?\s*(?<name>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)\s*(?<operator><>|<=|>=|=|<|>)\s*(?<value>[^()]+?)\s*\)?$");

        readonly Unit _unit;
        readonly Section _section;
        readonly RuleContext _context;
        readonly bool _pointers;
        readonly int _end;
        Dictionary<string, double> _constants;
        readonly Dictionary<string, double?> _settled = new Dictionary<string, double?>(StringComparer.OrdinalIgnoreCase);

        // pointers: the names are pointers, so ADR(...) and "p + n" from a
        // non-null p are non-null.
        internal NonZeroFlow(Unit unit, RuleContext context, bool pointers)
        {
            _unit = unit; _section = unit.Body; _context = context; _pointers = pointers;
            _end = _section.At(_section.Text.Length);
        }

        // true: non-zero at offset; false: zero for certain; null: unknown.
        internal bool? At(string name, int offset) => Guarded(name, offset, 0);

        bool? Guarded(string name, int offset, int depth)
        {
            if (Number(name) is double constant && constant != 0) return true;
            Func<string, bool?> test = condition => RulesOutZero(condition, name);
            Func<string, bool?> otherwise = condition => Failing(condition, name);
            var unchanged = Guards.Unchanged(_section, name, offset);
            var state = Guards.At(_unit.Tree, offset, test, otherwise, unchanged);
            if (state != null) return state;
            if (Guards.ExitsBefore(_section, offset, otherwise, unchanged)) return true;
            return depth < Deepest && Assigned(name, offset, depth) ? true : (bool?)null;
        }

        // The last "name := value;" before offset: on the use's path with a
        // non-zero value, or the only arm of an IF without ELSE closed before
        // the use, setting non-zero when the IF's condition holds for zero
        // (otherwise what held before the IF still holds).
        bool Assigned(string name, int offset, int depth)
        {
            var last = Guards.Assignment(name).Matches(_section.Text.Substring(0, offset - _section.Base)).Cast<Match>().LastOrDefault();
            if (last == null) return false;
            var at = _section.At(last.Index);
            if (!NonZero(last.Groups["value"].Value, at, depth)) return false;
            var use = _unit.Tree.PathTo(offset, _end);
            if (use.StartsWith(_unit.Tree.PathTo(at, _end), StringComparison.Ordinal)) return true;
            var block = _unit.Tree;
            for (Block child; (child = block.Children.FirstOrDefault(candidate => candidate.Start <= at && at < (candidate.End ?? _end))) != null;) block = child;
            if (block.Kind != "IF" || block.Branches.Count != 1 || !(block.End <= offset)) return false;
            var around = _unit.Tree.PathTo(block.Start, _end).TrimEnd('/');
            if (!use.StartsWith(around.Substring(0, around.LastIndexOf('/') + 1), StringComparison.Ordinal)) return false;
            return Guards.Whole(block.Branches[0].Label, condition => HoldsForZero(condition, name)) == true || Guarded(name, block.Start, depth + 1) == true;
        }

        // A value that is never zero: a non-zero number or constant, a name
        // or a conversion of a name non-zero there, LIMIT with a positive low
        // bound, MAX with a positive argument; for a pointer also ADR(...)
        // and an offset from a non-null pointer.
        bool NonZero(string value, int at, int depth)
        {
            value = value.Trim();
            if (Number(value) is double number) return number != 0;
            if (Name.IsMatch(value)) return Guarded(value, at, depth + 1) == true;
            if (_pointers && Address.IsMatch(value)) return true;
            var offset = Offset.Match(value);
            if (_pointers && offset.Success) return Guarded(offset.Groups["name"].Value, at, depth + 1) == true;
            var call = Function.Match(value);
            if (!call.Success) return false;
            var function = call.Groups["function"].Value;
            var arguments = call.Groups["arguments"].Value.Split(',').Select(argument => argument.Trim()).ToList();
            if (Conversion.IsMatch(function))
                return arguments.Count == 1 && Name.IsMatch(arguments[0]) && Guarded(arguments[0], at, depth + 1) == true;
            if (function.Equals("LIMIT", StringComparison.OrdinalIgnoreCase))
                return arguments.Count == 3 && Number(arguments[0]) > 0;
            return function.Equals("MAX", StringComparison.OrdinalIgnoreCase) && arguments.Any(argument => Number(argument) > 0);
        }

        // A comparison of name (dotted, any spacing) with a number or a
        // constant: true when it rules out zero ("x <> 0", "x > 0",
        // "x >= MIN_COUNT"), false when it proves it ("x = 0"), else null.
        bool? RulesOutZero(string condition, string name)
        {
            var holds = HoldsForZero(condition, name);
            if (holds != true) return holds == false ? true : (bool?)null;
            var comparison = Compared(condition, name).Value;
            return comparison.Key == "=" && comparison.Value == 0 ? false : (bool?)null;
        }

        // What a comparison of name failing proves: non-zero when zero meets
        // it ("x <= 0", "x < MIN"), zero when it is "x <> 0", else nothing.
        bool? Failing(string condition, string name)
        {
            if (HoldsForZero(condition, name) == true) return true;
            var comparison = Compared(condition, name);
            return comparison?.Key == "<>" && comparison?.Value == 0 ? false : (bool?)null;
        }

        // Whether zero meets a comparison of name with a number ("x < 5",
        // "x <= MIN", "x = 0"); null when the condition is not one.
        bool? HoldsForZero(string condition, string name)
        {
            if (!(Compared(condition, name) is KeyValuePair<string, double> comparison)) return null;
            var value = comparison.Value;
            switch (comparison.Key)
            {
                case "<": return 0 < value;
                case "<=": return 0 <= value;
                case "=": return value == 0;
                case "<>": return value != 0;
                case ">": return 0 > value;
                default: return 0 >= value;
            }
        }

        // The operator and the number name is compared with.
        KeyValuePair<string, double>? Compared(string condition, string name)
        {
            var match = Comparison.Match(condition);
            if (!match.Success || !StText.Unspaced(match.Groups["name"].Value).Equals(StText.Unspaced(name), StringComparison.OrdinalIgnoreCase)) return null;
            return Number(match.Groups["value"].Value) is double value ? new KeyValuePair<string, double>(match.Groups["operator"].Value, value) : (KeyValuePair<string, double>?)null;
        }

        // A literal, a constant the unit sees or a local no code changes, as
        // a number.
        double? Number(string text)
        {
            text = text.Trim();
            if ((_constants ?? (_constants = Constants())).TryGetValue(StText.Unspaced(text), out var constant)) return constant;
            if (StText.IsIdentifier(text)) return _settled.TryGetValue(text, out var settled) ? settled : _settled[text] = Settled(text);
            return Numeric(StConstants.Value(text));
        }

        static double? Numeric(object value) => value is BigInteger whole ? (double)whole : value is double real ? real : (double?)null;

        // A local of the unit or of its program or function block (VAR,
        // VAR_TEMP, VAR_STAT; not RETAIN or PERSISTENT) declared with a number
        // that no code of its owner assigns, passes to an output, a VAR_IN_OUT,
        // ADR or REF=, and no screen or other XML names; for a program also
        // no "P.name" elsewhere. Its declared value is all it ever holds.
        double? Settled(string name)
        {
            foreach (var holder in new[] { _unit, _context.Snapshot.InstanceOwner(_unit) }.Where(unit => unit != null))
            {
                var member = holder.VarBlocks.Where(block => Locals.Contains(block.Scope) && !block.Retain && !block.Persistent).SelectMany(block => block.Members)
                    .FirstOrDefault(candidate => candidate.Name.Equals(name, StringComparison.OrdinalIgnoreCase));
                if (member == null) continue;
                var value = Numeric(StConstants.Value(member.Initial ?? ""));
                if (value == null || _context.External.Names(name)) return null;
                foreach (var code in new[] { holder }.Concat(_context.Snapshot.OwnedBy(holder.QualifiedName)))
                    if (StBlocks.Written(code.Body.Text).Contains(name) || _context.Graph.InOutArguments(code).Contains(name, StringComparer.OrdinalIgnoreCase)
                        || Referenced.Matches(code.Body.Text).Cast<Match>().Any(match => match.Groups["name"].Value.Equals(name, StringComparison.OrdinalIgnoreCase)))
                        return null;
                if (holder.Kind != Kinds.Program) return value;
                var outside = new Regex(@"\b" + Regex.Escape(holder.QualifiedName.Split('.').Last()) + @"\s*\.\s*" + Regex.Escape(name) + @"\b", RegexOptions.IgnoreCase);
                return _context.Units.Any(unit => outside.IsMatch(unit.Body.Text)) ? null : value;
            }
            return null;
        }

        // The constants the unit sees whose declared value is a number: its
        // own and its owner's, and the GVLs' by both names.
        Dictionary<string, double> Constants()
        {
            var names = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
            var owner = _context.Snapshot.InstanceOwner(_unit);
            foreach (var holder in new[] { _unit, owner }.Where(u => u != null).Concat(_context.Units.Where(u => Kinds.IsGlobals(u.Kind))))
                foreach (var member in holder.VarBlocks.Where(block => block.Constant).SelectMany(block => block.Members))
                {
                    if (!(Numeric(StConstants.Value(member.Initial ?? "")) is double number)) continue;
                    names[member.Name] = number;
                    if (Kinds.IsGlobals(holder.Kind)) names[holder.QualifiedName + "." + member.Name] = number;
                }
            return names;
        }
    }
}
