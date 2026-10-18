using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public class StHighlightTests
    {
        static string[] Kinds(string text)
        {
            return StHighlight.Tokens(text)
                .Select(token => token.Kind + " " + text.Substring(token.Start, token.Length))
                .ToArray();
        }

        [Fact]
        public void KeywordsTypesAndLiteralsAreTokensAndNamesAreNot()
        {
            var text = "IF bRun AND nCount < 10 THEN\n  sName := 'it''s $'ok$'';\n  x := INT#-5;\nend_if\nVAR a : DINT; END_VAR";
            Assert.Equal(new[]
            {
                "Keyword IF", "Keyword AND", "Number 10", "Keyword THEN",
                "Text 'it'", "Text 's $'ok$''",
                "Number INT#-5", "Keyword end_if",
                "Keyword VAR", "Type DINT", "Keyword END_VAR",
            }, Kinds(text));
        }

        [Fact]
        public void CommentsNestAndPragmasRunToTheirBrace()
        {
            var text = "{attribute 'hide'}\nx := 1; // IF not a keyword\n(* outer (* inner *) still IF *) THEN";
            Assert.Equal(new[]
            {
                "Pragma {attribute 'hide'}", "Number 1", "Comment // IF not a keyword",
                "Comment (* outer (* inner *) still IF *)", "Keyword THEN",
            }, Kinds(text));
        }

        [Fact]
        public void TypedLiteralsHoldTogetherWhileCaseLabelsAndArithmeticStayApart()
        {
            var text = "CASE n OF\n1: t := T#1h2m;\n16#FF: d := DT#2024-01-02-03:04:05;\n2: y := 5-3 + 1.5E-3;\nEND_CASE";
            Assert.Equal(new[]
            {
                "Keyword CASE", "Keyword OF",
                "Number 1", "Number T#1h2m",
                "Number 16#FF", "Number DT#2024-01-02-03:04:05",
                "Number 2", "Number 5", "Number 3", "Number 1.5E-3",
                "Keyword END_CASE",
            }, Kinds(text));
        }

        [Fact]
        public void TheRtfColoursTokensAndEscapesTheRest()
        {
            var palette = new StPalette { Ink = 0x010203, Keyword = 0x0A0B0C };
            var rtf = StHighlight.Rtf("IF a THEN\r\n\tb := '{x}\\é';", "Consolas", 9.5f, palette);
            Assert.StartsWith(@"{\rtf1\ansi\deff0{\fonttbl{\f0\fmodern Consolas;}}{\colortbl ;\red1\green2\blue3;\red10\green11\blue12;", rtf);
            Assert.Contains(@"}\f0\fs19\cf1 \cf2 IF\cf1  a \cf2 THEN\cf1 \par" + "\n" + @"\tab b := \cf6 '\{x\}\\\u233?'\cf1 ;}", rtf);
        }
    }
}
