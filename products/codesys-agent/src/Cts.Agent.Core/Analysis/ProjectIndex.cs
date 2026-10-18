using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis
{
    // Names of the standard IEC 61131-3 and CODESYS library symbols.
    internal static class Library
    {
        static readonly HashSet<string> Functions = new HashSet<string>
        {
            "ABS", "ACOS", "ASIN", "ATAN", "COS", "EXP", "LN", "LOG", "SIN", "SQRT", "TAN",
            "SEL", "MAX", "MIN", "LIMIT", "MUX", "GT", "GE", "EQ", "LE", "LT", "NE",
            "SHL", "SHR", "ROL", "ROR", "LEFT", "RIGHT", "MID", "LEN", "FIND", "REPLACE", "INSERT", "DELETE",
            "CONCAT", "MOVE", "DEREF", "ADR", "REF", "SIZEOF",
            "TO_STRING", "TO_WSTRING", "TRUNC", "INT", "REAL", "LREAL", "DINT", "UDINT",
            "WORD", "DWORD", "BYTE", "BOOL", "TIME", "DATE", "DT", "TOD",
            "STRING", "WSTRING", "LOWER_BOUND", "UPPER_BOUND", "TRUNC_INT",
            "WCONCAT", "WLEFT", "WRIGHT", "WMID", "WLEN", "WFIND", "WREPLACE", "WINSERT", "WDELETE",
            "SYSMEMCPY", "SYSSOCKBIND", "SYSSOCKCLOSE", "SYSSOCKCREATE", "SYSSOCKGETOPTION", "SYSSOCKHTONS", "SYSSOCKINETADDR",
            "SYSSOCKIOCTL", "SYSSOCKRECVFROM", "SYSSOCKSENDTO", "SYSSOCKSETOPTION", "SYSSOCKSHUTDOWN", "SYSSOCKPING",
            "CMADDCOMPONENT2", "COMPONENT_MANAGER.CMADDCOMPONENT2", "CMPLOG.LOGADD2", "IECTASKGETCURRENT", "IECTASKGETINFO3", "SYSTIMEGETMS",
        };

        internal static readonly string[] FunctionBlocks = { "TON", "TOF", "TP", "R_TRIG", "F_TRIG", "SR", "RS", "CTU", "CTD", "CTUD", "PID", "INTEGRAL", "DERIVATIVE" };
        static readonly Regex Conversion = new Regex(@"^[A-Z][A-Z0-9]*_TO_[A-Z][A-Z0-9]*$");

        // A library function, IEC conversions (DINT_TO_LREAL, TO_...) included.
        internal static bool IsFunction(string name)
        {
            var upper = (name ?? "").Trim().ToUpperInvariant();
            return Functions.Contains(upper) || upper.StartsWith("TO_", StringComparison.Ordinal) || Conversion.IsMatch(upper);
        }

        internal static bool IsFunctionBlock(string name) => FunctionBlocks.Contains(Snapshot.LastSegment(name).ToUpperInvariant());
    }

    // One read or write of a project global in an implementation.
    internal sealed class GlobalAccess
    {
        internal Unit Unit, Global;
        internal VarMember Member;
        internal string Target;
        internal bool Write;
        internal int Offset, EndOffset;
        // Qualified paths are explicit; a bare name is resolved by being unique.
        internal string Confidence;
    }

    internal sealed class GlobalAccessIndex
    {
        static readonly Regex PathName = new Regex(@"\b(?<path>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)\b");
        static readonly Regex QualifiedOnly = new Regex(@"\{\s*attribute\s+'qualified_only'\s*\}", RegexOptions.IgnoreCase);
        readonly Dictionary<string, Tuple<Unit, VarMember>> _qualified = new Dictionary<string, Tuple<Unit, VarMember>>(StringComparer.OrdinalIgnoreCase);
        readonly Dictionary<string, Tuple<Unit, VarMember>> _bare = new Dictionary<string, Tuple<Unit, VarMember>>(StringComparer.OrdinalIgnoreCase);
        readonly HashSet<string> _ambiguous = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        internal GlobalAccessIndex(Snapshot snapshot)
        {
            foreach (var unit in snapshot.Units.Where(unit => Kinds.IsGlobals(unit.Kind)))
                foreach (var member in unit.Members().Where(m => m.Name.Length > 0))
                {
                    _qualified[unit.QualifiedName + "." + member.Name] = Tuple.Create(unit, member);
                    // A qualified_only list's variables have no bare name.
                    if (QualifiedOnly.IsMatch(unit.Text ?? "")) continue;
                    if (_bare.TryGetValue(member.Name, out var known) && known.Item1.Id != unit.Id) _ambiguous.Add(member.Name);
                    else _bare[member.Name] = Tuple.Create(unit, member);
                }
        }

        Tuple<Unit, VarMember> Resolve(string[] parts, HashSet<string> locals)
        {
            if (parts.Length == 1)
                return locals.Contains(parts[0]) || _ambiguous.Contains(parts[0]) ? null : _bare.TryGetValue(parts[0], out var bare) ? bare : null;
            if (locals.Contains(parts[0])) return null;
            for (var count = parts.Length; count > 1; count--)
                if (_qualified.TryGetValue(string.Join(".", parts.Take(count)), out var found)) return found;
            return null;
        }

        // Every global variable a bare name reaches, a name two GVLs declare
        // once.
        internal IEnumerable<VarMember> Members => _bare.Values.Select(global => global.Item2);

        // A global variable a bare name reaches exists, in one GVL or several.
        internal bool Declares(string name) => _bare.ContainsKey(name);

        internal List<GlobalAccess> AccessesFor(Unit unit)
        {
            var found = new List<GlobalAccess>();
            if (!Kinds.IsCallable(unit.Kind) || unit.Body.IsEmpty) return found;
            var section = unit.Body;
            var locals = new HashSet<string>(unit.Members().Where(m => m.Name.Length > 0).Select(m => m.Name), StringComparer.OrdinalIgnoreCase);
            foreach (Match match in PathName.Matches(section.Text))
            {
                var parts = match.Groups["path"].Value.Split('.').Select(part => part.Trim()).ToArray();
                var resolved = Resolve(parts, locals);
                if (resolved == null) continue;
                found.Add(new GlobalAccess
                {
                    Unit = unit, Global = resolved.Item1, Member = resolved.Item2, Target = string.Join(".", parts),
                    Write = StBlocks.AssignsAt(section.Text, match.Index + match.Length),
                    Offset = section.At(match.Index), EndOffset = section.At(match.Index + match.Length),
                    Confidence = parts.Length > 1 ? "high" : "medium",
                });
            }
            return found;
        }
    }

    // FB types, global members and pointers several rules look up.
    internal static class ProjectLookup
    {
        static readonly Regex Pointer = new Regex(@"^POINTER\s+TO\s+(?<base>.+)$", RegexOptions.IgnoreCase | RegexOptions.Singleline);

        // Lower-case names of the project's FB types and the standard ones.
        internal static HashSet<string> FunctionBlockTypes(RuleContext context)
        {
            var names = new HashSet<string>(Library.FunctionBlocks.Select(n => n.ToLowerInvariant()));
            foreach (var unit in context.Units.Where(unit => unit.Kind == Kinds.FunctionBlock))
            {
                names.Add(unit.QualifiedName.ToLowerInvariant());
                names.Add(Snapshot.LastSegment(unit.QualifiedName).ToLowerInvariant());
            }
            return names;
        }

        internal static bool IsFunctionBlockType(string type, HashSet<string> names)
        {
            var text = (type ?? "").Trim().ToLowerInvariant();
            return text.Length > 0 && (names.Contains(text) || names.Contains(Snapshot.LastSegment(text)) || Library.IsFunctionBlock(text));
        }

        // Global members by lower-case name; a name two GVLs declare is left out.
        internal static Dictionary<string, Tuple<Unit, VarMember>> GlobalMembers(RuleContext context)
        {
            var found = new Dictionary<string, Tuple<Unit, VarMember>>();
            var ambiguous = new HashSet<string>();
            foreach (var unit in context.Units.Where(unit => Kinds.IsGlobals(unit.Kind)))
                foreach (var member in unit.Members().Where(m => m.Name.Length > 0))
                {
                    var key = member.Name.ToLowerInvariant();
                    if (found.TryGetValue(key, out var known) && known.Item1.Id != unit.Id) ambiguous.Add(key);
                    else found[key] = Tuple.Create(unit, member);
                }
            return found.Where(p => !ambiguous.Contains(p.Key)).ToDictionary(p => p.Key, p => p.Value);
        }

        // The pointed-to type in lower case, null for a non-pointer.
        internal static string PointerBase(string type)
        {
            var match = Pointer.Match((type ?? "").Trim());
            return match.Success ? Regex.Replace(match.Groups["base"].Value.Trim(), @"\s+", " ").ToLowerInvariant() : null;
        }

        // The unit's own pointer members and the globals' (the unit's win).
        internal static Dictionary<string, Tuple<string, string>> PointerMembers(Unit unit, RuleContext context)
        {
            var result = new Dictionary<string, Tuple<string, string>>();
            foreach (var member in context.Snapshot.MembersSeenBy(unit))
            {
                var pointed = PointerBase(member.Type);
                if (member.Name.Length > 0 && pointed != null && !result.ContainsKey(member.Name.ToLowerInvariant())) result[member.Name.ToLowerInvariant()] = Tuple.Create(member.Name, pointed);
            }
            foreach (var global in context.Units.Where(u => Kinds.IsGlobals(u.Kind)))
                foreach (var member in global.Members())
                {
                    var pointed = PointerBase(member.Type);
                    var key = member.Name.ToLowerInvariant();
                    if (member.Name.Length > 0 && pointed != null && !result.ContainsKey(key)) result[key] = Tuple.Create(member.Name, pointed);
                }
            return result;
        }
    }
}
