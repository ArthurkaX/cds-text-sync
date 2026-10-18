using System;
using System.Collections.Generic;
using Xunit;

namespace Cts.Agent.Tests
{
    // ObjectFields reaches an IDE object through its own members by name, so a
    // plain class with the same members drives it exactly as CODESYS does: the
    // interface names below are the only thing the code reads about the type.
    public class ObjectFieldsTests
    {
        interface IArchivable
        {
            string[] SerializableValueNames { get; }
            object GetSerializableValue(string name);
            void SetSerializableValue(string name, object value);
        }

        interface ITextDocument { }

        sealed class Document : ITextDocument { }

        enum Kind { Cyclic, Freewheeling }

        sealed class Node : IArchivable
        {
            readonly Dictionary<string, object> _values = new Dictionary<string, object>();

            public Node Set(string name, object value) { _values[name] = value; return this; }

            public string[] SerializableValueNames
            {
                get { return new List<string>(_values.Keys).ToArray(); }
            }

            public object GetSerializableValue(string name)
            {
                object value;
                if (!_values.TryGetValue(name, out value)) throw new ArgumentException("no such name: " + name);
                return value;
            }

            public void SetSerializableValue(string name, object value)
            {
                if (!_values.ContainsKey(name)) throw new ArgumentException("no such name: " + name);
                _values[name] = value;
            }
        }

        // ---- paths

        [Fact]
        public void APathIsNameStepsWithListIndices()
        {
            var steps = ObjectFields.ParsePath("TextList[0].LanguageTexts[12]");
            Assert.Equal(2, steps.Count);
            Assert.Equal("TextList", steps[0].Name);
            Assert.Equal(0, steps[0].Index);
            Assert.True(steps[0].IsIndexed);
            Assert.Equal("LanguageTexts", steps[1].Name);
            Assert.Equal(12, steps[1].Index);

            var plain = ObjectFields.ParsePath("Watchdog.Time.Time");
            Assert.Equal(3, plain.Count);
            Assert.Equal("Time", plain[2].Name);
            Assert.False(plain[1].IsIndexed);
            Assert.Equal(-1, plain[1].Index);
        }

        [Theory]
        [InlineData("")]
        [InlineData(".a")]
        [InlineData("a.")]
        [InlineData("a..b")]
        [InlineData("TextList[x]")]
        [InlineData("TextList[]")]
        [InlineData("TextList[1")]
        [InlineData("TextList[-1]")]
        [InlineData("[0]")]
        public void AMalformedPathIsRefused(string path)
        {
            var error = Assert.Throws<ProtocolException>(() => ObjectFields.ParsePath(path));
            Assert.Equal(ErrorCodes.BadParams, error.Code);
        }

        // ---- the tree

        [Fact]
        public void ScalarsArriveAsTheirTextAndNestedMembersAsObjects()
        {
            var task = new Node()
                .Set("Priority", 1)
                .Set("Kindoftask", Kind.Freewheeling)
                .Set("AllowEmpty", true)
                .Set("TaskGuid", new Guid("2d749aa7-6e89-40d6-843c-7359127b84d3"))
                .Set("Implicit", null)
                .Set("Interval", new Node().Set("Time", 4).Set("Unit", "ms"))
                .Set("PouList", new List<object> { new Node().Set("Name", "Main").Set("Comment", null) })
                .Set("Attributes", new Dictionary<object, object> { { "a", "b" } });

            var fields = ObjectFields.Tree(task, 4);

            Assert.Equal("1", fields["Priority"]);
            Assert.Equal("Freewheeling", fields["Kindoftask"]);
            Assert.Equal("True", fields["AllowEmpty"]);
            Assert.Equal("2d749aa7-6e89-40d6-843c-7359127b84d3", fields["TaskGuid"]);
            Assert.Null(fields["Implicit"]);

            var interval = Assert.IsType<Dictionary<string, object>>(fields["Interval"]);
            Assert.Equal("4", interval["Time"]);
            Assert.Equal("ms", interval["Unit"]);

            var calls = Assert.IsType<List<object>>(fields["PouList"]);
            var call = Assert.IsType<Dictionary<string, object>>(Assert.Single(calls));
            Assert.Equal("Main", call["Name"]);
            Assert.Null(call["Comment"]);

            var attributes = Assert.IsType<Dictionary<string, object>>(fields["Attributes"]);
            Assert.Equal("b", attributes["a"]);
        }

        [Fact]
        public void TheTextAndWhatCodesysRegeneratesAreLeftOut()
        {
            var pou = new Node()
                .Set("POULevel", "Standard")
                .Set("UniqueIdGenerator", "volatile")
                .Set("Interface", new Node().Set("TextDocument", new Document()))
                .Set("Implementation", new Node().Set("TextDocument", new Document()).Set("Language", "ST"))
                .Set("LastVisuLanguageModelEntry", new Node().Set("LanguageModelData", "volatile"))
                .Set("TextDocument", new Document());

            var fields = ObjectFields.Tree(pou, 4);

            Assert.False(fields.ContainsKey("UniqueIdGenerator"));
            Assert.False(fields.ContainsKey("Interface"));
            Assert.False(fields.ContainsKey("TextDocument"));
            // Implementation holds more than the text, so it stays -- without it.
            var implementation = Assert.IsType<Dictionary<string, object>>(fields["Implementation"]);
            Assert.Equal("ST", implementation["Language"]);
            Assert.False(implementation.ContainsKey("TextDocument"));
            // A container is not dropped for being empty; the volatile member
            // inside it is.
            var entry = Assert.IsType<Dictionary<string, object>>(fields["LastVisuLanguageModelEntry"]);
            Assert.Empty(entry);
            Assert.Equal("Standard", fields["POULevel"]);
        }

        // A kind with an unset member (an unexpanded visual element colour)
        // must not fail: IsText asks the null value for a text interface.
        [Fact]
        public void ANullMemberIsNotTextAndDoesNotFailTheRead()
        {
            var visual = new Node()
                .Set("VisualElemList", new Node().Set("BgGradient", null))
                .Set("TextDocument", new Document());

            var fields = ObjectFields.Tree(visual, 4);

            Assert.False(fields.ContainsKey("TextDocument"));
            var element = Assert.IsType<Dictionary<string, object>>(fields["VisualElemList"]);
            Assert.Null(element["BgGradient"]);
        }

        [Fact]
        public void DepthLimitsWhatIsExpanded()
        {
            var node = new Node().Set("Level1", new Node().Set("Level2", new Node().Set("Leaf", 7)));

            var shallow = ObjectFields.Tree(node, 1);
            Assert.Empty(Assert.IsType<Dictionary<string, object>>(shallow["Level1"]));

            var none = ObjectFields.Tree(node, 0);
            Assert.Empty(Assert.IsType<Dictionary<string, object>>(none["Level1"]));

            var deep = ObjectFields.Tree(node, 3);
            var level2 = Assert.IsType<Dictionary<string, object>>(
                Assert.IsType<Dictionary<string, object>>(deep["Level1"])["Level2"]);
            Assert.Equal("7", level2["Leaf"]);

            // A depth no archive reaches is capped, not followed: a chain far
            // deeper than the cap stops at it instead of recursing away.
            var chain = new Node().Set("Leaf", 1);
            for (var i = 0; i < 40; i++) chain = new Node().Set("Next", chain);
            var level = ObjectFields.Tree(chain, 10000);
            var levels = 0;
            while (level.ContainsKey("Next"))
            {
                level = Assert.IsType<Dictionary<string, object>>(level["Next"]);
                levels++;
            }
            Assert.Equal(ObjectFields.MaxDepth, levels);
            Assert.Empty(level);
        }

        [Fact]
        public void AListOfRowsIsAnArrayOfObjects()
        {
            var list = new Node().Set("Languages", new List<object> { "de", "en" }).Set("TextList", new List<object>
            {
                new Node().Set("TextID", "212").Set("TextDefault", "Start").Set("GuidInit", "volatile"),
                new Node().Set("TextID", "213").Set("TextDefault", "Stop"),
            });

            var fields = ObjectFields.Tree(list, 3);

            Assert.Equal(new List<object> { "de", "en" }, fields["Languages"]);
            var rows = Assert.IsType<List<object>>(fields["TextList"]);
            Assert.Equal(2, rows.Count);
            var second = Assert.IsType<Dictionary<string, object>>(rows[1]);
            Assert.Equal("213", second["TextID"]);
            Assert.Equal("Stop", second["TextDefault"]);
            Assert.False(second.ContainsKey("GuidInit"));
        }

        [Fact]
        public void AThingThatIsNotAnArchivableCannotBeWalked()
        {
            var error = Assert.Throws<ProtocolException>(() => ObjectFields.Tree(new object(), 4));
            Assert.Equal(ErrorCodes.BadParams, error.Code);
        }

        // ---- reading one step

        [Fact]
        public void AStepFollowsAListIndex()
        {
            var row = new Node().Set("TextDefault", "Start");
            var list = new Node().Set("TextList", new List<object> { row });

            var item = ObjectFields.Get(list, new FieldStep("TextList", 0));
            Assert.Same(row, item);
            Assert.Equal("Start", ObjectFields.Get(item, new FieldStep("TextDefault", -1)));
        }

        [Fact]
        public void AStepTheObjectDoesNotHaveIsRefusedWithWhatItHas()
        {
            var task = new Node().Set("Priority", 1).Set("Watchdog", new Node());

            var error = Assert.Throws<ProtocolException>(() => ObjectFields.Get(task, new FieldStep("Prio", -1)));
            Assert.Equal(ErrorCodes.BadParams, error.Code);
            Assert.Contains("Prio", error.Message);
            Assert.Contains("Priority", error.Message);
            Assert.Contains("Watchdog", error.Message);
        }

        [Fact]
        public void AnIndexNothingHasAndANameThatIsNotAListAreRefused()
        {
            var list = new Node().Set("TextList", new List<object> { new Node().Set("TextID", "212") });
            var tooFar = Assert.Throws<ProtocolException>(() => ObjectFields.Get(list, new FieldStep("TextList", 1)));
            Assert.Contains("1 items", tooFar.Message);

            var row = ObjectFields.Get(list, new FieldStep("TextList", 0));
            var notAList = Assert.Throws<ProtocolException>(() => ObjectFields.Get(row, new FieldStep("TextID", 0)));
            Assert.Equal(ErrorCodes.BadParams, notAList.Code);
            Assert.Contains("not a list", notAList.Message);
        }

        [Fact]
        public void AWriteTouchesOneFieldOrOneListItem()
        {
            var row = new Node().Set("TextDefault", "Start").Set("TextID", "212");
            ObjectFields.Write(row, new FieldStep("TextDefault", -1),
                FieldValue.Convert("Start (t75)", row.GetSerializableValue("TextDefault")));
            Assert.Equal("Start (t75)", row.GetSerializableValue("TextDefault"));
            Assert.Equal("212", row.GetSerializableValue("TextID"));

            var languages = new List<object> { "de", "en" };
            var list = new Node().Set("Languages", languages);
            ObjectFields.Write(list, new FieldStep("Languages", 1), "fr");
            Assert.Equal(new List<object> { "de", "fr" }, languages);
        }

        [Fact]
        public void APathWalksDownToAnItem()
        {
            var list = new Node().Set("Languages", new List<object> { "de" })
                .Set("TextList", new List<object> { new Node().Set("LanguageTexts", new List<object> { "Start" }) });

            var steps = ObjectFields.ParsePath("TextList[0].LanguageTexts[0]");
            Assert.Equal("Start", ObjectFields.Walk(list, steps));

            var parent = ObjectFields.Walk(list, steps.GetRange(0, steps.Count - 1));
            Assert.Equal("Start", ObjectFields.Get(parent, steps[1]));
        }

        // ---- converting one value

        [Fact]
        public void AValueKeepsTheTypeOfTheFieldItReplaces()
        {
            Assert.Equal("Start", FieldValue.Convert("Start", "old"));
            Assert.Equal("Start", FieldValue.Convert("Start", null));
            Assert.Equal(12, (int)FieldValue.Convert("12", 1));
            Assert.Equal(1.5, (double)FieldValue.Convert("1.5", 2.5));
            Assert.True((bool)FieldValue.Convert("true", false));
            Assert.Equal(Kind.Freewheeling, (Kind)FieldValue.Convert("Freewheeling", Kind.Cyclic));
            var guid = new Guid("2d749aa7-6e89-40d6-843c-7359127b84d3");
            Assert.Equal(guid, (Guid)FieldValue.Convert(guid.ToString(), Guid.Empty));
            Assert.Equal("Gr\u00f6\u00dfe", FieldValue.Convert("Gr\u00f6\u00dfe", "Gross"));
        }

        [Theory]
        [InlineData("abc", 1)]
        [InlineData("1.5", 1)]
        [InlineData("", 1)]
        public void AValueTheTypeCannotHoldIsRefused(string text, int old)
        {
            var error = Assert.Throws<ProtocolException>(() => FieldValue.Convert(text, old));
            Assert.Equal(ErrorCodes.BadParams, error.Code);
        }

        [Fact]
        public void AValueOutsideTheFieldsRangeIsRefusedRatherThanWrapped()
        {
            var error = Assert.Throws<ProtocolException>(() => FieldValue.Convert("40000", (short)1));
            Assert.Equal(ErrorCodes.BadParams, error.Code);
        }

        [Fact]
        public void AnEnumValueIsWrittenByNameOnly()
        {
            var error = Assert.Throws<ProtocolException>(() => FieldValue.Convert("cyclic", Kind.Cyclic));
            Assert.Equal(ErrorCodes.BadParams, error.Code);
        }

        [Fact]
        public void AVolatileNameIsRecognisedWhereverItAppears()
        {
            Assert.True(ObjectFields.IsVolatile("LineInfoPersistence"));
            Assert.True(ObjectFields.IsVolatile("GuidReInit"));
            Assert.False(ObjectFields.IsVolatile("TaskGuid"));
            Assert.False(ObjectFields.IsVolatile("lineinfopersistence"));
        }
    }
}
