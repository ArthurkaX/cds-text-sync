// Minimal Structured Text colouring for the read-only code panes (the format
// window, the FSM map): keywords, type names, comments, pragmas, string and
// numeric literals.  A lexer good enough to colour, not to parse: an
// unterminated comment or string runs to the end of the text, an identifier
// followed by `#` (T#1s, INT#5, 16#FF) reads as one literal.
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace Cts.Agent
{
    public enum StTokenKind
    {
        Keyword,
        Type,
        Comment,
        Pragma,
        Text,
        Number,
    }

    public sealed class StToken
    {
        public int Start { get; internal set; }
        public int Length { get; internal set; }
        public StTokenKind Kind { get; internal set; }
    }

    //: Colours as 0xRRGGBB: the plain text and one per token kind.
    public sealed class StPalette
    {
        public int Ink { get; set; }
        public int Keyword { get; set; }
        public int Type { get; set; }
        public int Comment { get; set; }
        public int Pragma { get; set; }
        public int Text { get; set; }
        public int Number { get; set; }
    }

    public static class StHighlight
    {
        static readonly HashSet<string> Keywords = Words(
            "IF THEN ELSIF ELSE END_IF CASE OF END_CASE FOR TO BY DO END_FOR WHILE END_WHILE REPEAT UNTIL END_REPEAT "
            + "EXIT CONTINUE RETURN JMP AND OR XOR NOT MOD AND_THEN OR_ELSE TRUE FALSE "
            + "VAR VAR_INPUT VAR_OUTPUT VAR_IN_OUT VAR_GLOBAL VAR_TEMP VAR_STAT VAR_INST VAR_EXTERNAL VAR_CONFIG END_VAR "
            + "CONSTANT RETAIN PERSISTENT AT FUNCTION END_FUNCTION FUNCTION_BLOCK END_FUNCTION_BLOCK PROGRAM END_PROGRAM "
            + "METHOD END_METHOD PROPERTY END_PROPERTY ACTION END_ACTION INTERFACE END_INTERFACE TYPE END_TYPE "
            + "STRUCT END_STRUCT UNION END_UNION EXTENDS IMPLEMENTS ABSTRACT FINAL PUBLIC PRIVATE PROTECTED INTERNAL "
            + "THIS SUPER ARRAY POINTER REFERENCE");

        static readonly HashSet<string> Types = Words(
            "BOOL BYTE WORD DWORD LWORD SINT INT DINT LINT USINT UINT UDINT ULINT REAL LREAL "
            + "TIME LTIME DATE LDATE TIME_OF_DAY LTIME_OF_DAY TOD LTOD DATE_AND_TIME LDATE_AND_TIME DT LDT "
            + "STRING WSTRING CHAR WCHAR ANY __XWORD __UXINT __XINT");

        public static List<StToken> Tokens(string text)
        {
            var tokens = new List<StToken>();
            var i = 0;
            while (i < text.Length)
            {
                var c = text[i];
                var start = i;
                if (c == '/' && At(text, i + 1, '/'))
                {
                    i = LineEnd(text, i);
                    tokens.Add(Token(start, i, StTokenKind.Comment));
                }
                else if (c == '(' && At(text, i + 1, '*'))
                {
                    i = CommentEnd(text, i);
                    tokens.Add(Token(start, i, StTokenKind.Comment));
                }
                else if (c == '{')
                {
                    i = After(text, i + 1, '}');
                    tokens.Add(Token(start, i, StTokenKind.Pragma));
                }
                else if (c == '\'' || c == '"')
                {
                    i = StringEnd(text, i);
                    tokens.Add(Token(start, i, StTokenKind.Text));
                }
                else if (char.IsDigit(c))
                {
                    i = NumberEnd(text, i);
                    tokens.Add(Token(start, i, StTokenKind.Number));
                }
                else if (char.IsLetter(c) || c == '_')
                {
                    i = WordEnd(text, i);
                    if (At(text, i, '#'))
                    {
                        i = NumberEnd(text, i);
                        tokens.Add(Token(start, i, StTokenKind.Number));
                        continue;
                    }
                    var word = text.Substring(start, i - start);
                    if (Keywords.Contains(word))
                        tokens.Add(Token(start, i, StTokenKind.Keyword));
                    else if (Types.Contains(word))
                        tokens.Add(Token(start, i, StTokenKind.Type));
                }
                else
                {
                    i++;
                }
            }
            return tokens;
        }

        //: The text as RTF in one font, coloured; line breaks become paragraphs.
        public static string Rtf(string text, string font, float points, StPalette palette)
        {
            var rtf = new StringBuilder(text.Length * 2 + 256);
            rtf.Append(@"{\rtf1\ansi\deff0{\fonttbl{\f0\fmodern ").Append(font).Append(";}}{\\colortbl ;");
            foreach (var colour in new[] { palette.Ink, palette.Keyword, palette.Type, palette.Comment, palette.Pragma, palette.Text, palette.Number })
            {
                rtf.Append(@"\red").Append((colour >> 16) & 0xFF);
                rtf.Append(@"\green").Append((colour >> 8) & 0xFF);
                rtf.Append(@"\blue").Append(colour & 0xFF).Append(';');
            }
            rtf.Append(@"}\f0\fs").Append(((int)System.Math.Round(points * 2)).ToString(CultureInfo.InvariantCulture)).Append(@"\cf1 ");
            var at = 0;
            foreach (var token in Tokens(text))
            {
                Escape(rtf, text, at, token.Start);
                rtf.Append(@"\cf").Append((int)token.Kind + 2).Append(' ');
                Escape(rtf, text, token.Start, token.Start + token.Length);
                rtf.Append(@"\cf1 ");
                at = token.Start + token.Length;
            }
            Escape(rtf, text, at, text.Length);
            return rtf.Append('}').ToString();
        }

        static void Escape(StringBuilder rtf, string text, int from, int to)
        {
            for (var i = from; i < to; i++)
            {
                var c = text[i];
                if (c == '\r')
                    continue;
                if (c == '\n')
                    rtf.Append("\\par\n");
                else if (c == '\t')
                    rtf.Append(@"\tab ");
                else if (c == '\\' || c == '{' || c == '}')
                    rtf.Append('\\').Append(c);
                else if (c > 127)
                    rtf.Append(@"\u").Append((short)c).Append('?');
                else
                    rtf.Append(c);
            }
        }

        static HashSet<string> Words(string words)
        {
            return new HashSet<string>(words.Split(' '), System.StringComparer.OrdinalIgnoreCase);
        }

        static StToken Token(int start, int end, StTokenKind kind)
        {
            return new StToken { Start = start, Length = end - start, Kind = kind };
        }

        static bool At(string text, int i, char c)
        {
            return i < text.Length && text[i] == c;
        }

        static int LineEnd(string text, int i)
        {
            var end = text.IndexOf('\n', i);
            return end < 0 ? text.Length : end;
        }

        //: Past the `*)` closing the comment at i; comments nest.
        static int CommentEnd(string text, int i)
        {
            var depth = 0;
            while (i < text.Length)
            {
                if (text[i] == '(' && At(text, i + 1, '*'))
                {
                    depth++;
                    i += 2;
                }
                else if (text[i] == '*' && At(text, i + 1, ')'))
                {
                    depth--;
                    i += 2;
                    if (depth == 0)
                        return i;
                }
                else
                {
                    i++;
                }
            }
            return i;
        }

        static int After(string text, int i, char close)
        {
            var end = text.IndexOf(close, i);
            return end < 0 ? text.Length : end + 1;
        }

        //: Past the closing quote; `$` escapes the next character.
        static int StringEnd(string text, int i)
        {
            var quote = text[i];
            i++;
            while (i < text.Length)
            {
                if (text[i] == '$')
                {
                    i += 2;
                    continue;
                }
                if (text[i] == quote)
                    return i + 1;
                if (text[i] == '\n')
                    return i;
                i++;
            }
            return text.Length;
        }

        static int WordEnd(string text, int i)
        {
            while (i < text.Length && (char.IsLetterOrDigit(text[i]) || text[i] == '_'))
                i++;
            return i;
        }

        //: Digits, letters, `_`, `#` and a `.` before a digit (16#FF, 1.5E-3, T#1h2m); after a `#` also
        //: `:` and a sign before a digit (DT#2024-01-02-03:04:05, INT#-5), without one a sign only after
        //: an exponent, so `5-3` and the case label `1:` stay apart.
        static int NumberEnd(string text, int i)
        {
            var typed = false;
            while (i < text.Length)
            {
                var c = text[i];
                var digitNext = i + 1 < text.Length && char.IsDigit(text[i + 1]);
                if (c == '#')
                    typed = true;
                if (char.IsLetterOrDigit(c) || c == '_' || c == '#' || (c == ':' && typed && digitNext) || (c == '.' && digitNext))
                {
                    i++;
                    continue;
                }
                var signed = typed || text[i - 1] == 'e' || text[i - 1] == 'E';
                if ((c == '-' || c == '+') && digitNext && signed)
                {
                    i++;
                    continue;
                }
                break;
            }
            return i;
        }
    }
}
