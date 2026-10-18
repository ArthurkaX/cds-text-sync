using System;
using System.Collections.Generic;
using Xunit;

namespace Cts.Agent.Tests
{
    // objects.listadd / objects.listremove against plain stand-ins with the
    // members CODESYS rows have: IArchivable by name, ICloneable deep.
    public class ListEditTests
    {
        interface IArchivable
        {
            string[] SerializableValueNames { get; }
            object GetSerializableValue(string name);
            void SetSerializableValue(string name, object value);
        }

        sealed class Row : IArchivable, ICloneable
        {
            readonly Dictionary<string, object> _values = new Dictionary<string, object>
            {
                { "TextID", "" }, { "TextDefault", "" }, { "LanguageTexts", new List<object>() },
            };

            public Row Set(string name, object value) { _values[name] = value; return this; }

            public string[] SerializableValueNames { get { return new List<string>(_values.Keys).ToArray(); } }

            public object GetSerializableValue(string name) { return _values[name]; }

            public void SetSerializableValue(string name, object value) { _values[name] = value; }

            public object Clone()
            {
                var copy = new Row();
                foreach (var kv in _values)
                    copy._values[kv.Key] = kv.Value is List<object> ? new List<object>((List<object>)kv.Value) : kv.Value;
                return copy;
            }
        }

        sealed class Holder : IArchivable
        {
            public object Rows;
            public string[] SerializableValueNames { get { return new[] { "TextList" }; } }
            public object GetSerializableValue(string name) { return Rows; }
            public void SetSerializableValue(string name, object value) { Rows = value; }
        }

        static Row R(string id, string text, params string[] languages)
        {
            return new Row().Set("TextID", id).Set("TextDefault", text).Set("LanguageTexts", new List<object>(languages));
        }

        static Dictionary<string, object> Fields(string id, string text, params string[] languages)
        {
            var fields = new Dictionary<string, object> { { "TextID", id }, { "TextDefault", text } };
            for (var i = 0; i < languages.Length; i++) fields["LanguageTexts[" + i + "]"] = languages[i];
            return fields;
        }

        [Fact]
        public void AnInsertCopiesTheLastRowAndSetsEveryNamedField()
        {
            var rows = new List<object> { R("212", "Start", "Start de"), R("", "", "") };
            var holder = new Holder { Rows = rows };

            var list = ListEdit.Find(holder, "TextList");
            ListEdit.Insert(list, 1, Fields("213", "Stop", "Stopp"));

            Assert.Equal(3, rows.Count);
            var added = (Row)rows[1];
            Assert.Equal("213", added.GetSerializableValue("TextID"));
            Assert.Equal("Stop", added.GetSerializableValue("TextDefault"));
            Assert.Equal(new List<object> { "Stopp" }, added.GetSerializableValue("LanguageTexts"));
            // The copy is its own: the source row's texts are untouched.
            Assert.Equal(new List<object> { "" }, ((Row)rows[2]).GetSerializableValue("LanguageTexts"));
        }

        [Fact]
        public void AnInsertAtTheStartOrEndKeepsTheOtherRowsInOrder()
        {
            var rows = new List<object> { R("212", "Start") };
            var list = ListEdit.Find(new Holder { Rows = rows }, "TextList");

            ListEdit.Insert(list, 0, Fields("211", "First"));
            ListEdit.Insert(list, 2, Fields("213", "Last"));

            Assert.Equal(new[] { "211", "212", "213" },
                rows.ConvertAll(r => (string)((Row)r).GetSerializableValue("TextID")).ToArray());
        }

        [Fact]
        public void AnInsertPastTheEndOrABadFieldLeavesTheListAlone()
        {
            var rows = new List<object> { R("212", "Start") };
            var list = ListEdit.Find(new Holder { Rows = rows }, "TextList");

            var tooFar = Assert.Throws<ProtocolException>(() => ListEdit.Insert(list, 2, Fields("213", "x")));
            Assert.Equal(ErrorCodes.BadParams, tooFar.Code);
            // LanguageTexts[0] does not exist on a row with no languages.
            Assert.Throws<ProtocolException>(() => ListEdit.Insert(list, 1, Fields("213", "x", "y")));
            Assert.Single(rows);
        }

        [Fact]
        public void AnEmptyListCreatesItsItemType()
        {
            var rows = new List<Row>();
            var list = ListEdit.Find(new Holder { Rows = rows }, "TextList");

            ListEdit.Insert(list, 0, Fields("212", "Start"));

            Assert.Equal("212", rows[0].GetSerializableValue("TextID"));
        }

        [Fact]
        public void AnEmptyUntypedListIsRefused()
        {
            var list = ListEdit.Find(new Holder { Rows = new List<object>() }, "TextList");
            var error = Assert.Throws<ProtocolException>(() => ListEdit.Insert(list, 0, Fields("212", "Start")));
            Assert.Contains("item type", error.Message);
        }

        [Fact]
        public void ARemoveTakesOneRowAndRefusesAnIndexOutsideTheList()
        {
            var rows = new List<object> { R("212", "Start"), R("213", "Stop") };
            var list = ListEdit.Find(new Holder { Rows = rows }, "TextList");

            ListEdit.RemoveAt(list, 0);
            Assert.Equal("213", ((Row)rows[0]).GetSerializableValue("TextID"));
            Assert.Throws<ProtocolException>(() => ListEdit.RemoveAt(list, 1));
            Assert.Throws<ProtocolException>(() => ListEdit.RemoveAt(list, -1));
        }

        [Fact]
        public void APathMustNameAListNotAnItemOrAScalar()
        {
            var request = new Request(1, "objects.listremove", new Dictionary<string, object> { { "path", "TextList[0]" } });
            Assert.Throws<ProtocolException>(() => ListEdit.ListPath(request));

            var holder = new Holder { Rows = "not a list" };
            var error = Assert.Throws<ProtocolException>(() => ListEdit.Find(holder, "TextList"));
            Assert.Contains("not a list", error.Message);
        }

        [Fact]
        public void AnInsertRequestNeedsAPositionAndFieldsAsAnObject()
        {
            var noAt = new Request(1, "objects.listadd", new Dictionary<string, object> { { "path", "TextList" } });
            Assert.Throws<ProtocolException>(() => ListInsert.From(noAt));

            var badFields = new Request(1, "objects.listadd", new Dictionary<string, object>
            {
                { "path", "TextList" }, { "at", 0L }, { "fields", "TextID=1" },
            });
            Assert.Throws<ProtocolException>(() => ListInsert.From(badFields));

            var ok = ListInsert.From(new Request(1, "objects.listadd", new Dictionary<string, object>
            {
                { "path", "TextList" }, { "at", 1L }, { "fields", new Dictionary<string, object> { { "TextID", "213" } } },
            }));
            Assert.Equal(1, ok.At);
            Assert.Equal("213", ok.Fields["TextID"]);
        }
    }
}
