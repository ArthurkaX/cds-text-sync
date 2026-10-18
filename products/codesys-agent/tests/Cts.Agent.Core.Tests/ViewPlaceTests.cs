using System;
using System.IO;
using Cts.Visu;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class ViewPlaceTests : IDisposable
    {
        readonly string _view = Path.Combine(Path.GetTempPath(), "cts-viewplace-" + Guid.NewGuid().ToString("N"));

        public ViewPlaceTests()
        {
            Directory.CreateDirectory(Path.Combine(_view, "PLC", "Plc Logic", "Application"));
            File.WriteAllText(Path.Combine(_view, "PLC", "Plc Logic", "Application", "MAIN.st"), "");
        }

        public void Dispose() => Directory.Delete(_view, true);

        [Fact]
        public void A_folder_matches_whatever_its_case()
        {
            Assert.Equal(Path.Combine(_view, "PLC", "Plc Logic", "Application"), ViewPlace.ExistingFolder(_view, "PLC/PLC Logic/application"));
        }

        [Fact]
        public void A_missing_folder_names_the_folders_that_hold_objects()
        {
            var error = Assert.Throws<VisuException>(() => ViewPlace.ExistingFolder(_view, "Runtime/PLC Logic/Application/HMI"));
            Assert.Equal("No folder 'Runtime/PLC Logic/Application/HMI' in the project view. Folders that hold objects: PLC/Plc Logic/Application", error.Message);
        }
    }
}
