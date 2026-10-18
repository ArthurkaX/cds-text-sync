using System.Collections.Generic;
using System.Linq;
using System.Xml.Linq;
using Xunit;
using Cts.Visu;

namespace Cts.Agent.Tests
{
    public class ElementTemplatesTests
    {
        [Fact]
        public void An_element_goes_into_the_empty_screen_codesys_writes_self_closed()
        {
            var screen = "<Single Type=\"{6198ad31-4b98-445c-927f-3258a0e82fe3}\">"
                + "<Single Name=\"SizeX\" Type=\"int\">800</Single>"
                + "<Single Name=\"SizeY\" Type=\"int\">480</Single>"
                + "<List Name=\"VisualElementList\" Type=\"{ef9d0b20-c96e-48db-b361-2ded4063150e}\" />"
                + "<List Name=\"Hotkeys\" Type=\"System.Collections.ArrayList\" /></Single>";
            var parameters = new Dictionary<string, object> { ["x"] = "20", ["y"] = "20", ["width"] = "120", ["height"] = "40" };
            var output = ElementTemplates.Append(screen, VisuCatalog.Load("rectangle"), parameters, null,
                Themes.Palette("light", null), "light").Xml;
            var lists = XDocument.Parse(output).Descendants("List").ToList();
            Assert.Single(lists[0].Elements());
            Assert.Empty(lists[1].Elements());
        }
    }
}
