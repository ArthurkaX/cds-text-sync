using System.Collections.Generic;
using System.Linq;
using System.Xml.Linq;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    public sealed class StPragmaTests
    {
        [Fact]
        public void SettingsGoThroughThePragmaInCatalogOrderDefaultsLeftOut()
        {
            var settings = new Dictionary<string, string>
            {
                { "POULevel", "Global" }, { "CompilerDefines", "SIM,DEBUG" }, { "External", "True" }, { "LinkAlways", "False" }, { "SpecialFunc", "None" },
            };
            var line = StPragma.Format(null, settings);
            Assert.Equal("(* cds-text-sync: External CompilerDefines=\"SIM,DEBUG\" POULevel=\"Global\" *)", line);
            var parsed = StPragma.Parse(line, out var typeGuid);
            Assert.Null(typeGuid);
            Assert.Equal(new Dictionary<string, string> { { "External", "True" }, { "CompilerDefines", "SIM,DEBUG" }, { "POULevel", "Global" } }, parsed);
        }

        [Fact]
        public void AnUnknownNameAndADefaultValueAreDropped()
        {
            var parsed = StPragma.Parse("(* cds-text-sync: TypeGuid=\"{C2CDA7A9-0BA4-4146-B563-22A42FA0EB72}\" Shiny ExcludeFromBuild MemoryReserveForOnlineChange=\"0\" linkalways=\"false\" *)", out var typeGuid);
            Assert.Equal("c2cda7a9-0ba4-4146-b563-22a42fa0eb72", typeGuid);
            Assert.Equal(new Dictionary<string, string> { { "ExcludeFromBuild", "True" } }, parsed);
        }

        [Fact]
        public void AValueThePragmaCannotHoldKeepsTheXmlBeside()
        {
            Assert.False(TextSettings.Outside(Entry("<Single Name=\"External\" Type=\"bool\">True</Single><Single Name=\"CompilerDefines\" Type=\"string\">SIM</Single>")));
            Assert.Equal(new Dictionary<string, string> { { "External", "True" }, { "CompilerDefines", "SIM" }, { "POULevel", "Global" } },
                StPragma.Read(Entry("<Single Name=\"External\" Type=\"bool\">True</Single><Single Name=\"CompilerDefines\" Type=\"string\">SIM</Single>")));
            Assert.True(TextSettings.Outside(Entry("<Single Name=\"CompilerDefines\" Type=\"string\">A=\"x\"</Single>")));
        }

        [Fact]
        public void APersistentVariableListNeedsNoXmlBeside()
        {
            var entry = XElement.Parse("<Single><Single Name=\"MetaObject\" /><Single Name=\"Object\"><Null Name=\"persvarlist\" /><Single Name=\"Interface\" />"
                + "<Null Name=\"NetVarProperties\" /><Single Name=\"guidinit\">7c4fd1b2-765c-48b5-9304-7adccb1b6eb1</Single>"
                + "<Single Name=\"guidcyclic\">f5591abd-826f-424a-90cb-80159e6bdbd7</Single><Single Name=\"dymmattributecount\">0</Single></Single>"
                + "<Single Name=\"ParentSVNodeGuid\">dbff9c3f-8f12-464d-b9b4-815a6b768fbd</Single><Single Name=\"Index\">-1</Single></Single>");
            Assert.False(TextSettings.Outside(entry));
            entry.Descendants().Single(element => (string)element.Attribute("Name") == "dymmattributecount").Value = "2";
            Assert.True(TextSettings.Outside(entry));
        }

        // A POU entry at level Global with these build property fields.
        static XElement Entry(string buildFields) => XElement.Parse(
            "<Single><Single Name=\"MetaObject\"><Dictionary Name=\"Properties\"><Entry><Key><Single>" + StPragma.BuildProperty + "</Single></Key>"
            + "<Value><Single>" + buildFields + "</Single></Value></Entry></Dictionary></Single>"
            + "<Single Name=\"Object\"><Single Name=\"POULevel\">Global</Single><Single Name=\"UniqueIdGenerator\">3</Single></Single></Single>");
    }
}
