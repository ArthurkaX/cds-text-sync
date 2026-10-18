using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis
{
    // The parentheses and arguments of a call in implementation text; a
    // string literal's parentheses and commas do not count.
    internal static class StCalls
    {
        // A named function-style call in implementation text.
        internal static readonly Regex Call = new Regex(@"\b(?<name>[A-Za-z_]\w*)\s*\(");
        // An ADR call naming a variable.
        internal static readonly Regex AddressOf = new Regex(@"\bADR\s*\(\s*(?<name>[A-Za-z_]\w*)\s*\)", RegexOptions.IgnoreCase);

        // The ')' closing the '(' at opening, else -1.
        internal static int Close(string text, int opening)
        {
            var depth = 0;
            for (var index = opening; index < text.Length; index++)
            {
                var character = text[index];
                if (character == '\'' || character == '"') index = QuoteEnd(text, index);
                else if (character == '(') depth++;
                else if (character == ')' && --depth == 0) return index;
            }
            return -1;
        }

        // The '(' of the innermost call left open before offset, else -1.
        internal static int Opening(string text, int offset)
        {
            var depth = 0;
            for (var index = offset - 1; index >= 0; index--)
            {
                if (text[index] == ')') depth++;
                else if (text[index] == '(' && depth-- == 0) return index;
            }
            return -1;
        }

        // Whether offset is inside the parentheses of a call: the innermost
        // '(' left open before it follows a name (F, inst.M).
        internal static bool InArgument(string text, int offset)
        {
            var opening = Opening(text, offset);
            return opening >= 0 && Callee.IsMatch(text, opening);
        }

        static readonly Regex Callee = new Regex(@"[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)?\s*\G", RegexOptions.RightToLeft);

        // The comma-separated arguments of an argument list, trimmed.
        internal static List<string> Arguments(string text)
        {
            var arguments = new List<string>();
            var start = 0;
            var depth = 0;
            for (var index = 0; index < text.Length; index++)
            {
                var character = text[index];
                if (character == '\'' || character == '"') index = QuoteEnd(text, index);
                else if (character == '(') depth++;
                else if (character == ')') depth--;
                else if (character == ',' && depth == 0)
                {
                    arguments.Add(text.Substring(start, index - start).Trim());
                    start = index + 1;
                }
            }
            arguments.Add(text.Substring(start).Trim());
            return arguments;
        }

        // The closing quote of the literal opening at start ('$' escapes, doubled quotes).
        static int QuoteEnd(string text, int start)
        {
            var quote = text[start];
            for (var index = start + 1; index < text.Length; index++)
            {
                if (text[index] == '$') index++;
                else if (text[index] == quote)
                {
                    if (index + 1 < text.Length && text[index + 1] == quote) index++;
                    else return index;
                }
            }
            return text.Length;
        }
    }
}
