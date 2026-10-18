using System;
using System.Collections.Generic;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public class ObjectLookupTests
    {
        static ObjectRecord Record(string id, string name, string type, string parent = null) => new ObjectRecord
        {
            Guid = id,
            Name = name,
            Type = type,
            Parent = parent == null ? Guid.Empty : System.Guid.Parse(parent)
        };

        static List<ObjectRecord> Project() => new List<ObjectRecord>
        {
            Record("00000000-0000-0000-0000-000000000001", "Plant", "Project"),
            Record("00000000-0000-0000-0000-000000000002", "Plc Logic", "Folder", "00000000-0000-0000-0000-000000000001"),
            Record("00000000-0000-0000-0000-000000000003", "App1", "Application", "00000000-0000-0000-0000-000000000002"),
            Record("00000000-0000-0000-0000-000000000004", "BACKGROUND", "POU", "00000000-0000-0000-0000-000000000003"),
            Record("00000000-0000-0000-0000-000000000005", "BACKGROUND", "Task", "00000000-0000-0000-0000-000000000002"),
            Record("00000000-0000-0000-0000-000000000006", "App2", "Application", "00000000-0000-0000-0000-000000000002"),
            Record("00000000-0000-0000-0000-000000000007", "BACKGROUND", "POU", "00000000-0000-0000-0000-000000000006"),
            Record("00000000-0000-0000-0000-000000000008", "BACKGROUND", "Task", "00000000-0000-0000-0000-000000000001")
        };

        [Fact]
        public void BuildsPathByWalkingParentsToEmptyGuidRoot()
        {
            var match = ObjectLookup.Match(Project(), "BACKGROUND", "Plant/Plc Logic/App1/BACKGROUND").Single();
            Assert.Equal("Plant/Plc Logic/App1/BACKGROUND", match["path"]);
        }

        [Fact]
        public void ParsesSlashSeparatedPathAndFindsExactPath()
        {
            var matches = ObjectLookup.Match(Project(), "", "Plant/Plc Logic/App1/BACKGROUND");
            Assert.Single(matches);
            Assert.Equal("BACKGROUND", matches[0]["name"]);
        }

        [Fact]
        public void ReturnsEverySameNameMatchWithItsOwnPath()
        {
            var matches = ObjectLookup.Match(Project(), "BACKGROUND", "");
            Assert.Equal(4, matches.Count);
            Assert.Equal(4, matches.Select(x => x["path"]).Distinct().Count());
        }

        [Fact]
        public void ApplicationFilterKeepsOnlyMatchesUnderThatApplication()
        {
            var matches = ObjectLookup.Match(Project(), "BACKGROUND", "", "App1");
            Assert.Single(matches);
            Assert.Equal("Plant/Plc Logic/App1/BACKGROUND", matches[0]["path"]);
        }
    }
}
