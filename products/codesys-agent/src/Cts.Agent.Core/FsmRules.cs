using System;
using System.Text.RegularExpressions;

namespace Cts.Agent
{
    internal static class FsmRules
    {
        static readonly Regex Phase = new Regex(@"(?i)(?:^|(?<=[_.]))(?:current|actual|curr|akt|act|cur)(?=[_.]|[A-Z0-9]|$)|_(?:current|actual|curr|akt|act|cur)$", RegexOptions.Compiled);
        static readonly Regex NextNew = new Regex(@"(?i)next|new", RegexOptions.Compiled);
        static readonly Regex NonAlphaNumeric = new Regex("[^A-Z0-9]", RegexOptions.Compiled);

        internal static string Normalize(string name)
        {
            var trimmed = Phase.Replace(name, "");
            var folded = NonAlphaNumeric.Replace(NextNew.Replace(trimmed.ToUpperInvariant(), ""), "");
            return folded.Length > 0 ? folded : NonAlphaNumeric.Replace(NextNew.Replace(name.ToUpperInvariant(), ""), "");
        }

        internal static bool SameFamily(string lhs, string head)
        {
            var left = FamilyKey(lhs);
            var right = FamilyKey(head);
            return String.Equals(left.Item1, right.Item1, StringComparison.OrdinalIgnoreCase)
                && String.Equals(left.Item2, right.Item2, StringComparison.Ordinal);
        }

        static Tuple<string, string> FamilyKey(string expression)
        {
            var value = expression.Trim();
            var dot = value.LastIndexOf('.');
            return dot < 0
                ? Tuple.Create("", Normalize(value))
                : Tuple.Create(value.Substring(0, dot).ToUpperInvariant(), Normalize(value.Substring(dot + 1)));
        }
    }
}
