using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // ADR of a value that lives only for one call (VAR_TEMP; VAR of a
    // function, method, action or accessor) kept past the call: assigned to
    // the result, to a member path, to an output, in-out, static, retained or
    // global variable, or to the function block's own variables from one of
    // its methods; or handed to a call or RETURN in the same statement, but
    // not to a runtime library call (see KeepsNone).
    internal sealed class CTS0051 : Rule
    {
        static readonly Regex Target = new Regex(@"(?<target>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)\s*:=\s*$");
        static readonly Regex Call = new Regex(@"\b[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)?\s*\([^;]*$");
        // A runtime library call (SysFileOpen, sysfile.SysFileWrite,
        // MEMCPY, ...) uses a pointer during the call and keeps none.
        static readonly Regex Synchronous = new Regex(@"(?:^|[^\w.])(?:[A-Za-z_]\w*\s*\.\s*)*(?:Sys|Mem)\w*\s*$", RegexOptions.IgnoreCase);
        static readonly Regex Callee = new Regex(@"(?<![\w.])(?<head>[A-Za-z_]\w*)(?<tail>(?:\s*\.\s*[A-Za-z_]\w*)*)\s*$");
        static readonly Regex Interface = new Regex(@"^I[A-Z]");
        static readonly Regex Return = new Regex(@"\bRETURN\s*$", RegexOptions.IgnoreCase);
        static readonly HashSet<string> LocalKinds = new HashSet<string> { Analysis.Kinds.Function, Analysis.Kinds.Method, Analysis.Kinds.Action, Analysis.Kinds.PropertyGet, Analysis.Kinds.PropertySet };
        static readonly HashSet<string> EscapingScopes = new HashSet<string> { "VAR_GLOBAL", "VAR_EXTERNAL", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_STAT" };

        internal CTS0051() : base("CTS0051", "Escaping address of local value", Analysis.Severity.Danger, "Correctness", "The address of a local or temporary value must not escape its lifetime.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var own = unit.VarBlocks.SelectMany(block => block.Members.Select(member => new { member.Name, block })).ToList();
            var locals = new HashSet<string>(own.Where(member => member.block.Scope == "VAR_TEMP" || member.block.Scope == "VAR" && LocalKinds.Contains(unit.Kind)).Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
            if (locals.Count == 0) yield break;
            var escaping = new HashSet<string>(own.Where(member => EscapingScopes.Contains(member.block.Scope) || member.block.Retain || member.block.Persistent).Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
            var ownNames = new HashSet<string>(own.Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
            var owner = context.Snapshot.InstanceOwner(unit);
            var ownerNames = new HashSet<string>(owner == null ? Enumerable.Empty<string>() : owner.Members().Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
            var result = Snapshot.LastSegment(unit.QualifiedName);
            var text = unit.Body.Text;
            foreach (Match match in StCalls.AddressOf.Matches(text))
            {
                var local = match.Groups["name"].Value;
                if (!locals.Contains(local)) continue;
                var start = text.LastIndexOf(';', match.Index == 0 ? 0 : match.Index - 1) + 1;
                var prefix = text.Substring(start, match.Index - start);
                var target = Target.Match(prefix);
                string message;
                if (target.Success && Escapes(Regex.Replace(target.Groups["target"].Value, @"\s+", ""), result, escaping, ownNames, ownerNames, context))
                    message = "address of local '" + local + "' escapes through destination '" + target.Groups["target"].Value.Replace(" ", "") + "'";
                else if (!Call.IsMatch(prefix) && !Return.IsMatch(prefix) || KeepsNone(prefix.Substring(0, Math.Max(StCalls.Opening(prefix, prefix.Length), 0)), unit, context)) continue;
                else message = "address of local '" + local + "' is passed out of its lifetime through a call";
                yield return Finding.In(unit, message, unit.Body.At(match.Index), unit.Body.At(match.Index + match.Length), "ADR(" + local + ")", match.Value);
            }
        }

        // A call that uses the pointer while it runs and keeps none: a runtime
        // library's (SysFileOpen, MEMCPY, CmpIecVarAccess.IecVarAccGetFirstInterface),
        // or a method of a library interface a variable holds (itfAcc.VarAccGetNode,
        // itfAcc an IIecVarAccess3 the project does not declare).
        static bool KeepsNone(string before, Unit unit, RuleContext context)
        {
            if (Synchronous.IsMatch(before)) return true;
            var callee = Callee.Match(before);
            if (!callee.Success) return false;
            var head = callee.Groups["head"].Value;
            if (context.Snapshot.LibraryProvides(head + Regex.Replace(callee.Groups["tail"].Value, @"\s+", ""))) return true;
            if (callee.Groups["tail"].Length == 0) return false;
            var type = context.Snapshot.MembersSeenBy(unit).FirstOrDefault(member => member.Name.Equals(head, StringComparison.OrdinalIgnoreCase))?.Type?.Trim();
            return type != null && Interface.IsMatch(Snapshot.LastSegment(type)) && context.Snapshot.ByName(Snapshot.LastSegment(type)).Count == 0;
        }

        static bool Escapes(string target, string result, HashSet<string> escaping, HashSet<string> own, HashSet<string> owner, RuleContext context) =>
            target.Contains('.') || target.Equals(result, StringComparison.OrdinalIgnoreCase) || escaping.Contains(target)
            || !own.Contains(target) && (owner.Contains(target) || context.Globals.Declares(target));
    }
}
