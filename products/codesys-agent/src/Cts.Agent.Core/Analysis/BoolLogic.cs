using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis
{
    // Conditions of boolean variables, NOT, AND, OR, XOR, TRUE, FALSE and
    // parentheses, put to every combination of their variables: whether an
    // IF/ELSIF chain leaves no case out, an arm of it can never run, or a
    // condition has one value whatever they are.
    internal static class BoolLogic
    {
        const int MaxVariables = 8;
        static readonly Regex Token = new Regex(@"\G\s*(?:[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*|\s*\[[^\[\]]*\])*|[()&])");
        // A call may change a variable a later condition reads.
        static readonly Regex Call = new Regex(@"(?<![\w.])(?!(?:NOT|AND|AND_THEN|OR|OR_ELSE|XOR|MOD)\b)[A-Za-z_]\w*\s*\(", RegexOptions.IgnoreCase);
        static readonly HashSet<string> Reserved = new HashSet<string> { "AND", "AND_THEN", "OR", "OR_ELSE", "XOR", "NOT", "MOD" };

        // Whether one of conditions holds whatever its variables are.
        internal static bool Exhaustive(IList<string> conditions) => Covered(conditions, "TRUE");

        // Whether condition holds only where one of earlier does, or never.
        // An earlier condition that is more than boolean logic (a
        // comparison) counts as never holding; a call anywhere gives false.
        internal static bool Covered(IList<string> earlier, string condition)
        {
            var variables = new Dictionary<string, int>(StringComparer.Ordinal);
            var tests = new List<Func<bool[], bool>>();
            foreach (var text in earlier.Where(text => text != null))
            {
                if (Call.IsMatch(text)) return false;
                var test = new Parser(text, variables).Read();
                if (test != null) tests.Add(test);
            }
            var target = Read(condition, variables);
            return target != null && variables.Count <= MaxVariables && Rows(variables.Count).All(values => !target(values) || tests.Any(test => test(values)));
        }

        // true or false when condition, over one variable or more, has that
        // value whatever they are; null otherwise.
        internal static bool? Constant(string condition)
        {
            var variables = new Dictionary<string, int>(StringComparer.Ordinal);
            var test = Read(condition, variables);
            if (test == null || variables.Count == 0 || variables.Count > MaxVariables) return null;
            var results = Rows(variables.Count).Select(values => test(values)).Distinct().ToList();
            return results.Count == 1 ? results[0] : (bool?)null;
        }

        static Func<bool[], bool> Read(string condition, Dictionary<string, int> variables) => Call.IsMatch(condition) ? null : new Parser(condition, variables).Read();

        // Every combination of count values, in one array reused.
        static IEnumerable<bool[]> Rows(int count)
        {
            var values = new bool[count];
            for (var row = 0; row < 1 << count; row++)
            {
                for (var bit = 0; bit < count; bit++) values[bit] = (row >> bit & 1) == 1;
                yield return values;
            }
        }

        sealed class Parser
        {
            readonly List<string> tokens = new List<string>();
            readonly Dictionary<string, int> variables;
            readonly bool failed;
            int at;

            internal Parser(string text, Dictionary<string, int> variables)
            {
                this.variables = variables;
                for (var match = Token.Match(text); match.Success; match = Token.Match(text, match.Index + match.Length))
                    tokens.Add(StText.Unspaced(match.Value).ToUpperInvariant());
                failed = Token.Replace(text, "").Trim().Length > 0;
            }

            // The condition as a test of the variables' values, null when it
            // is not plain boolean logic.
            internal Func<bool[], bool> Read()
            {
                if (failed) return null;
                var test = Or();
                return at == tokens.Count ? test : null;
            }

            Func<bool[], bool> Or() => Binary(Xor, (a, b) => a || b, "OR", "OR_ELSE");
            Func<bool[], bool> Xor() => Binary(And, (a, b) => a ^ b, "XOR");
            Func<bool[], bool> And() => Binary(Unary, (a, b) => a && b, "AND", "AND_THEN", "&");

            Func<bool[], bool> Binary(Func<Func<bool[], bool>> operand, Func<bool, bool, bool> join, params string[] words)
            {
                var left = operand();
                while (left != null && at < tokens.Count && words.Contains(tokens[at]))
                {
                    at++;
                    var right = operand();
                    if (right == null) return null;
                    var first = left;
                    left = values => join(first(values), right(values));
                }
                return left;
            }

            Func<bool[], bool> Unary()
            {
                if (at >= tokens.Count || tokens[at] != "NOT") return Primary();
                at++;
                var inner = Unary();
                return inner == null ? null : (Func<bool[], bool>)(values => !inner(values));
            }

            Func<bool[], bool> Primary()
            {
                if (at >= tokens.Count) return null;
                var token = tokens[at++];
                if (token == "(")
                {
                    var inner = Or();
                    if (inner == null || at >= tokens.Count || tokens[at] != ")") return null;
                    at++;
                    return inner;
                }
                if (token == "TRUE") return values => true;
                if (token == "FALSE") return values => false;
                // A call's result may change between two reads of it.
                if (token == ")" || token == "&" || Reserved.Contains(token) || at < tokens.Count && tokens[at] == "(") return null;
                if (!variables.TryGetValue(token, out var index)) variables[token] = index = variables.Count;
                return values => values[index];
            }
        }
    }
}
