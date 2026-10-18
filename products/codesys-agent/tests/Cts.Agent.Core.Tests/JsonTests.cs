using System.Collections.Generic;
using Xunit;

namespace Cts.Agent.Tests
{
    public class JsonTests
    {
        [Fact]
        public void ParsesScalars()
        {
            Assert.Null(Json.Parse("null"));
            Assert.Equal(true, Json.Parse("true"));
            Assert.Equal(false, Json.Parse(" false "));
            Assert.Equal(42L, Json.Parse("42"));
            Assert.Equal(-7L, Json.Parse("-7"));
            Assert.Equal(1.5, Json.Parse("1.5"));
            Assert.Equal(1000.0, Json.Parse("1e3"));
            Assert.Equal("hi", Json.Parse("\"hi\""));
        }

        [Fact]
        public void IntegerBeyondLongBecomesDouble()
        {
            Assert.IsType<double>(Json.Parse("123456789012345678901234567890"));
            Assert.Equal(long.MaxValue, Json.Parse("9223372036854775807"));
        }

        [Fact]
        public void ParsesNestedStructures()
        {
            var v = (IDictionary<string, object>)Json.Parse("{\"a\":[1,{\"b\":null}],\"c\":\"x\"}");
            var a = (IList<object>)v["a"];
            Assert.Equal(1L, a[0]);
            Assert.Null(((IDictionary<string, object>)a[1])["b"]);
            Assert.Equal("x", v["c"]);
        }

        [Fact]
        public void ParsesEmptyContainers()
        {
            Assert.Empty((IDictionary<string, object>)Json.Parse("{}"));
            Assert.Empty((IList<object>)Json.Parse("[ ]"));
        }

        [Theory]
        [InlineData("\"a\\nb\"", "a\nb")]
        [InlineData("\"q\\\"q\"", "q\"q")]
        [InlineData("\"s\\\\s\"", "s\\s")]
        [InlineData("\"\\u0041\"", "A")]
        [InlineData("\"\\u03a9\"", "\u03a9")]
        [InlineData("\"\\ud83d\\ude00\"", "\ud83d\ude00")]
        [InlineData("\"it$'s\"", "it$'s")]
        public void ParsesStringEscapes(string json, string expected)
        {
            Assert.Equal(expected, Json.Parse(json));
        }

        [Theory]
        [InlineData("")]
        [InlineData("{")]
        [InlineData("[1,]")]
        [InlineData("{\"a\":}")]
        [InlineData("{a:1}")]
        [InlineData("\"unterminated")]
        [InlineData("\"bad\\x\"")]
        [InlineData("\"\\u12\"")]
        [InlineData("01")]
        [InlineData("1.")]
        [InlineData("-")]
        [InlineData("tru")]
        [InlineData("1 2")]
        [InlineData("{} x")]
        public void RejectsMalformedInput(string json)
        {
            Assert.Throws<JsonException>(() => Json.Parse(json));
        }

        [Fact]
        public void RejectsRawControlCharacterInString()
        {
            Assert.Throws<JsonException>(() => Json.Parse("\"a\nb\""));
        }

        [Fact]
        public void RejectsDeepNesting()
        {
            var deep = new string('[', 100) + new string(']', 100);
            Assert.Throws<JsonException>(() => Json.Parse(deep));
        }

        [Fact]
        public void SerializesAndEscapes()
        {
            Assert.Equal("\"a\\nb\\\"c\\\\\"", Json.Serialize("a\nb\"c\\"));
            Assert.Equal("\"\\u0001\"", Json.Serialize("\u0001"));
            Assert.Equal("\"\\u2028\"", Json.Serialize("\u2028"));
            Assert.Equal("null", Json.Serialize(null));
            Assert.Equal("true", Json.Serialize(true));
            Assert.Equal("12", Json.Serialize(12));
            Assert.Equal("1.5", Json.Serialize(1.5));
        }

        [Fact]
        public void NonFiniteNumbersBecomeNull()
        {
            Assert.Equal("null", Json.Serialize(double.NaN));
            Assert.Equal("null", Json.Serialize(double.PositiveInfinity));
        }

        [Fact]
        public void SerializedTextNeverContainsALineBreak()
        {
            var json = Json.Serialize(new Dictionary<string, object> { { "k\n", "a\r\nb\u2029c" } });
            Assert.DoesNotContain("\n", json);
            Assert.DoesNotContain("\r", json);
            Assert.DoesNotContain("\u2029", json);
        }

        [Fact]
        public void SerializesDateTimeAsIsoUtc()
        {
            var t = new System.DateTime(2026, 10, 7, 12, 30, 5, 123, System.DateTimeKind.Utc);
            Assert.Equal("\"2026-10-07T12:30:05.123Z\"", Json.Serialize(t));
        }

        [Fact]
        public void RoundTrips()
        {
            var original = new Dictionary<string, object>
            {
                { "s", "\u0393\u03b5\u03b9\u03ac \"quoted\"\n" },
                { "n", 5L },
                { "list", new List<object> { 1L, "two", null, true } },
                { "nested", new Dictionary<string, object> { { "d", 2.25 } } },
            };
            var back = (IDictionary<string, object>)Json.Parse(Json.Serialize(original));
            Assert.Equal(original["s"], back["s"]);
            Assert.Equal(5L, back["n"]);
            Assert.Equal(4, ((IList<object>)back["list"]).Count);
            Assert.Equal(2.25, ((IDictionary<string, object>)back["nested"])["d"]);
        }

        [Fact]
        public void SerializeRejectsUnknownTypes()
        {
            Assert.Throws<JsonException>(() => Json.Serialize(new object()));
        }

        [Fact]
        public void PrettyIndentsByTwoAndSortsKeys()
        {
            var value = Json.Parse("{\"b\": [1, 2.0, 1e-05, true, null], \"a\": {}, \"c\": [], \"d\": {\"z\": \"\u00e9\\\"\\n\"}}");
            Assert.Equal("{\n  \"a\": {},\n  \"b\": [\n    1,\n    2.0,\n    1e-05,\n    true,\n    null\n  ],\n  \"c\": [],\n"
                + "  \"d\": {\n    \"z\": \"\\u00e9\\\"\\n\"\n  }\n}", Json.Pretty(value));
        }

        [Theory]
        [InlineData(4980.3948195, "4980.3948195")]
        [InlineData(0.1, "0.1")]
        [InlineData(1.0 / 3, "0.3333333333333333")]
        [InlineData(1e16, "1e+16")]
        public void PrettyWritesAFloatInItsShortestFormThatReadsBack(double value, string expected)
        {
            Assert.Equal(expected, Json.Pretty(value));
        }
    }
}
