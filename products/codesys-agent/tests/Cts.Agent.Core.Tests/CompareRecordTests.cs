using System.Collections.Generic;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    public sealed class CompareRecordTests
    {
        [Fact]
        public void AnswerKeepsEveryOptionalFieldAndOmitsImportState()
        {
            var record = new CompareRecord
            {
                Name = "Object",
                Path = "Object.st",
                Category = "modified",
                Reason = "changed",
                Parts = new List<string> { "declaration" },
                Guid = "guid",
                IdeChanged = true,
                Merges = true,
                Merged = new byte[] { 1 },
                ObjectPath = "Application.Object",
                Timestamp = 42,
                Kind = "program",
            };

            Assert.Equal("{\n  \"guid\": \"guid\",\n  \"ide_changed\": true,\n  \"merges\": true,\n  \"name\": \"Object\",\n  \"parts\": [\n    \"declaration\"\n  ],\n  \"path\": \"Object.st\",\n  \"reason\": \"changed\"\n}", Cts.Agent.Json.Pretty(record.Answer()));
        }
    }
}
