using System;
using System.Collections.Generic;
using System.Globalization;
using System.Numerics;
using System.Text.RegularExpressions;

namespace Cts.Analysis
{
    // The value of an expression of literals only, with ST precedence and
    // types: integer division truncates, MOD takes integers, AND/OR/XOR/NOT
    // take booleans only (on numbers they are bitwise). A bool, a
    // BigInteger or a double; null for anything else or a division by zero.
    internal static class StConstants
    {
        static readonly Regex Token = new Regex(@"\G\s*(?:(?<number>\d+#[0-9A-Fa-f_]+|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d+)(?:[eE][+-]?\d+)?)|(?<symbol><>|<=|>=|[=<>+\-*/()&])|(?<word>AND|OR|XOR|NOT|MOD|TRUE|FALSE)\b)", RegexOptions.IgnoreCase);

        internal static object Value(string text)
        {
            var tokens = Tokens(text);
            return tokens == null ? null : new Constant(tokens).Value();
        }

        static List<string> Tokens(string text)
        {
            var tokens = new List<string>();
            var position = 0;
            while (position < text.Length)
            {
                var token = Token.Match(text, position);
                if (!token.Success || token.Length == 0) return text.Substring(position).Trim().Length == 0 ? tokens : null;
                tokens.Add(token.Value.Trim().ToUpperInvariant());
                position += token.Length;
            }
            return tokens;
        }

        // Recursive descent over IEC 61131-3 precedence.
        sealed class Constant
        {
            readonly List<string> _tokens;
            int _next;

            internal Constant(List<string> tokens) { _tokens = tokens; }

            internal object Value()
            {
                var value = Or();
                return _next == _tokens.Count ? value : null;
            }

            string Peek => _next < _tokens.Count ? _tokens[_next] : null;

            bool Take(params string[] options)
            {
                if (Array.IndexOf(options, Peek) < 0) return false;
                _next++;
                return true;
            }

            object Or() => Logical(Xor, "OR", (a, b) => a | b);
            object Xor() => Logical(And, "XOR", (a, b) => a ^ b);
            object And() => Logical(Equality, "AND", (a, b) => a & b, "&");

            object Logical(Func<object> operand, string word, Func<bool, bool, bool> apply, string symbol = null)
            {
                var value = operand();
                while (Take(word, symbol ?? word))
                {
                    var right = operand();
                    value = value is bool a && right is bool b ? apply(a, b) : (object)null;
                }
                return value;
            }

            object Equality()
            {
                var value = Relational();
                while (Peek == "=" || Peek == "<>")
                {
                    var equal = _tokens[_next++] == "=";
                    var right = Relational();
                    var same = value is bool a && right is bool b ? a == b : Compare(value, right) is int order ? order == 0 : (bool?)null;
                    value = same.HasValue ? same.Value == equal : (object)null;
                }
                return value;
            }

            object Relational()
            {
                var value = Additive();
                while (Peek == "<" || Peek == ">" || Peek == "<=" || Peek == ">=")
                {
                    var symbol = _tokens[_next++];
                    var order = Compare(value, Additive());
                    value = order.HasValue ? (symbol == "<" ? order < 0 : symbol == ">" ? order > 0 : symbol == "<=" ? order <= 0 : order >= 0) : (object)null;
                }
                return value;
            }

            object Additive()
            {
                var value = Term();
                while (Peek == "+" || Peek == "-")
                {
                    var plus = _tokens[_next++] == "+";
                    value = Arithmetic(value, Term(), (a, b) => plus ? a + b : a - b, (a, b) => plus ? a + b : a - b);
                }
                return value;
            }

            object Term()
            {
                var value = Unary();
                while (Peek == "*" || Peek == "/" || Peek == "MOD")
                {
                    var symbol = _tokens[_next++];
                    var right = Unary();
                    if (symbol == "*") value = Arithmetic(value, right, (a, b) => a * b, (a, b) => a * b);
                    else if (right is BigInteger divisor && divisor.IsZero || right is double real && real == 0) value = null;
                    else if (symbol == "/") value = Arithmetic(value, right, BigInteger.Divide, (a, b) => a / b);
                    else value = value is BigInteger a && right is BigInteger b ? BigInteger.Remainder(a, b) : (object)null;
                }
                return value;
            }

            object Unary()
            {
                if (Take("-")) { var value = Unary(); return value is BigInteger a ? -a : value is double b ? -b : (object)null; }
                if (Take("+")) { var value = Unary(); return value is BigInteger || value is double ? value : null; }
                if (Take("NOT")) return Unary() is bool c ? !c : (object)null;
                return Primary();
            }

            object Primary()
            {
                var token = Peek;
                if (token == null) return null;
                _next++;
                if (token == "(")
                {
                    var value = Or();
                    return Take(")") ? value : null;
                }
                if (token == "TRUE") return true;
                if (token == "FALSE") return false;
                if (!char.IsDigit(token[0]) && token[0] != '.') return null;
                if (token.Contains("#")) return IecTypes.Integer(token);
                var digits = token.Replace("_", "");
                return digits.IndexOfAny(new[] { '.', 'E' }) >= 0
                    ? double.Parse(digits, CultureInfo.InvariantCulture)
                    : (object)BigInteger.Parse(digits, CultureInfo.InvariantCulture);
            }

            static object Arithmetic(object left, object right, Func<BigInteger, BigInteger, BigInteger> integers, Func<double, double, double> reals)
            {
                if (left is BigInteger a && right is BigInteger b) return integers(a, b);
                return Real(left) is double x && Real(right) is double y ? reals(x, y) : (object)null;
            }

            static int? Compare(object left, object right)
            {
                if (left is BigInteger a && right is BigInteger b) return a.CompareTo(b);
                return Real(left) is double x && Real(right) is double y ? x.CompareTo(y) : (int?)null;
            }

            static double? Real(object value) => value is double real ? real : value is BigInteger integer ? (double)integer : (double?)null;
        }
    }
}
