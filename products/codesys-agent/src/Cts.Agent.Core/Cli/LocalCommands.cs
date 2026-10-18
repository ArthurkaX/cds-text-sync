using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Agent;

namespace Cts.Cli
{
    // Commands served by cts.exe without discovering an IDE.
    public static class LocalCommands
    {
        // The one setting: the quick window's key, per user in defaults.json.
        const string QuickKeySetting = "quick_key";

        public static Answer GuideLine(IDictionary<string, object> data)
        {
            if (data.ContainsKey("topics"))
            {
                var rules = (IList<object>)data["rules"];
                var topics = ((IList<object>)data["topics"]).Cast<IDictionary<string, object>>().ToList();
                var index = new Answer().Add("rules", rules.Count).Add("topics", topics.Count).Whole().Detail("Rules:");
                foreach (var rule in rules) index.Detail("  - " + rule);
                index.Detail("Common jobs:");
                foreach (var job in (IList<object>)data["jobs"]) index.Detail("  - " + job);
                index.Detail("Topics:");
                foreach (var topic in topics) index.Detail(string.Format("  {0,-10} {1}", topic["topic"], topic["summary"]));
                return index;
            }
            var text = Convert.ToString(data["text"]);
            var answer = new Answer().Add("topic", data["topic"]);
            if (data.ContainsKey("section")) return answer.Add("section", data["section"]).Whole().Detail(text);
            answer.Add("files", data.ContainsKey("files") ? ((IList<string>)data["files"]).Count : 1).Whole();
            var headings = Headings(text);
            // The map's top: "##" sections, or the "###" ones of a guide that is one section.
            var top = new[] { 2, 3 }.FirstOrDefault(level => headings.Count(h => h.Level == level) >= 2);
            if (text.Length <= LongGuide || Equals(data["all"], true) || top == 0) return answer.Detail(text);
            // The opening, the first section, then the map of the rest.
            var second = headings.Where(h => h.Level == top).Skip(1).First();
            answer.Add("shown", "opening").Detail(text.Substring(0, second.Start).TrimEnd());
            answer.Detail("\nSections (" + Kilo(text.Length) + " in all):");
            foreach (var heading in headings.Where(h => h.Start >= second.Start))
                answer.Detail((heading.Level == top ? "  " : "      ") + heading.Title + "  " + Kilo(Part(text, headings, heading).Length));
            return answer.Detail("Next: cts guide " + data["topic"] + " --section \"<title>\" prints one section, --all the whole guide");
        }

        public static Answer ConfigLine(IDictionary<string, object> data)
        {
            var settings = data["settings"] as IDictionary<string, object>;
            var answer = new Answer().Add("keys", settings == null ? 0 : settings.Count).Whole();
            if (settings != null)
            {
                foreach (var pair in settings)
                {
                    var entry = (IDictionary<string, object>)pair.Value;
                    answer.Detail(pair.Key + " = " + Json.Serialize(entry["value"])
                        + "  (" + entry["source"] + ")");
                }
            }
            return answer;
        }

        public static Answer ChangeLine(IDictionary<string, object> data)
        {
            return new Answer()
                .Add("key", data["key"])
                .Add(data.ContainsKey("removed") ? "removed" : "value",
                    data.ContainsKey("removed") ? data["removed"] : (data.ContainsKey("value") ? data["value"] : null))
                .Add("note", data.ContainsKey("note") ? data["note"] : null);
        }

        public static IDictionary<string, object> Guide(CliOptions options)
        {
            var topic = options.Arguments.FirstOrDefault();
            var file = options.Params.ContainsKey("file") ? Convert.ToString(options.Params["file"]) : null;
            if (file != null && string.IsNullOrEmpty(topic)) throw Refuse("guide", "--file needs a topic");
            var index = ReadIndex();
            if (topic == null) return index;
            var topics = ((IList<object>)index["topics"]).Cast<IDictionary<string, object>>().ToList();
            var entry = topics.FirstOrDefault(item => Equals(item["topic"], topic));
            if (entry == null) throw Refuse("guide", Unknown(topic, topics));
            if (file != null)
            {
                if (file.Contains("..") || file.StartsWith("/") || file.Contains(":"))
                    throw Refuse("guide", "invalid guide file name '" + file + "'");
                var text = Resource("Cts.Agent.Guides." + topic + "/" + file);
                if (text == null)
                    throw Refuse("guide", "guide topic '" + topic + "' has no file '" + file + "'");
                return new Dictionary<string, object> { { "topic", topic }, { "file", file }, { "text", text } };
            }
            var body = entry.TryGetValue("section", out var section) ? Section(Convert.ToString(section)) : Resource("Cts.Agent.Guides." + topic + ".md");
            if (body == null) throw Refuse("guide", "guide topic '" + topic + "' is missing");
            var headings = Headings(body);
            var wanted = options.Text("section");
            if (wanted != null)
            {
                var matches = headings.Where(h => h.Title.Equals(wanted, StringComparison.OrdinalIgnoreCase)).ToList();
                if (matches.Count == 0) matches = headings.Where(h => h.Title.IndexOf(wanted, StringComparison.OrdinalIgnoreCase) >= 0).ToList();
                if (matches.Count != 1)
                    throw Refuse("guide", (matches.Count == 0 ? "guide " + topic + " has no section '" + wanted + "'" : "'" + wanted + "' matches " + matches.Count + " sections of guide " + topic)
                        + "; its sections: " + string.Join(", ", (matches.Count == 0 ? headings : matches).Select(h => h.Title)));
                return new Dictionary<string, object> { { "topic", topic }, { "section", matches[0].Title }, { "text", Part(body, headings, matches[0]) } };
            }
            var prefix = "Cts.Agent.Guides." + topic + "/";
            var files = typeof(LocalCommands).Assembly.GetManifestResourceNames()
                .Where(name => name.StartsWith(prefix, StringComparison.Ordinal))
                .Select(name => name.Substring(prefix.Length)).ToArray();
            return new Dictionary<string, object>
            {
                { "topic", topic }, { "text", body }, { "files", files }, { "all", options.Params.ContainsKey("all") },
                { "sections", headings.Select(h => (object)new Dictionary<string, object> { { "title", h.Title }, { "level", h.Level }, { "chars", Part(body, headings, h).Length } }).ToList() },
            };
        }

        static string Kilo(int chars) => (chars / 1000.0).ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + "k";

        // A guide longer than this prints its opening and a map of its
        // sections instead of the whole text.
        const int LongGuide = 12000;

        sealed class Heading
        {
            internal int Level;
            internal string Title;
            internal int Start;
        }

        // The guide's "## " and "### " headings, those inside code blocks left out.
        static List<Heading> Headings(string text)
        {
            var found = new List<Heading>();
            var fenced = false;
            for (var start = 0; start < text.Length;)
            {
                var end = text.IndexOf('\n', start);
                if (end < 0) end = text.Length;
                var line = text.Substring(start, end - start).TrimEnd('\r');
                if (line.StartsWith("```", StringComparison.Ordinal)) fenced = !fenced;
                else if (!fenced && (line.StartsWith("## ", StringComparison.Ordinal) || line.StartsWith("### ", StringComparison.Ordinal)))
                    found.Add(new Heading { Level = line.IndexOf(' '), Title = line.Substring(line.IndexOf(' ') + 1).Trim(), Start = start });
                start = end + 1;
            }
            return found;
        }

        // A section with its subsections: up to the next heading of its level or above.
        static string Part(string text, IList<Heading> headings, Heading heading)
        {
            var next = headings.FirstOrDefault(h => h.Start > heading.Start && h.Level <= heading.Level);
            return text.Substring(heading.Start, (next?.Start ?? text.Length) - heading.Start).TrimEnd() + "\n";
        }

        // A topic that is one section of a longer guide: "commands#Heading"
        // is that guide's "## Heading" or "### Heading" with its subsections.
        static string Section(string section)
        {
            var parts = section.Split('#');
            var text = Resource("Cts.Agent.Guides." + parts[0] + ".md");
            if (text == null) return null;
            var headings = Headings(text);
            var heading = headings.FirstOrDefault(h => h.Title == parts[1]);
            return heading == null ? null : Part(text, headings, heading);
        }

        // No such topic: the topics whose guides mention the word, else them all.
        static string Unknown(string topic, IList<IDictionary<string, object>> topics)
        {
            var word = topic.TrimEnd('s');
            var mentioning = topics.Where(item => (item.TryGetValue("section", out var section) ? Section(Convert.ToString(section)) : Resource("Cts.Agent.Guides." + item["topic"] + ".md"))
                ?.IndexOf(word, StringComparison.OrdinalIgnoreCase) >= 0).Select(item => Convert.ToString(item["topic"])).ToList();
            return "unknown guide topic '" + topic + "'; " + (mentioning.Count > 0
                ? "the guides that mention " + word + ": " + string.Join(", ", mentioning)
                : "valid topics: " + string.Join(", ", topics.Select(item => item["topic"])));
        }

        // The rules, the common jobs and the topics of bare `cts guide`.
        // The topics' names, for `cts guide --help`.
        internal static string TopicNames() =>
            string.Join(", ", ((IList<object>)ReadIndex()["topics"]).Cast<IDictionary<string, object>>().Select(topic => topic["topic"]));

        static IDictionary<string, object> ReadIndex() =>
            (IDictionary<string, object>)Json.Parse(Resource("Cts.Agent.Guides.index.json"));

        static string Resource(string path)
        {
            var assembly = typeof(LocalCommands).Assembly;
            var resource = assembly.GetManifestResourceNames().FirstOrDefault(name => name == path
                || name.EndsWith(path.Substring("Cts.Agent.Guides.".Length), StringComparison.Ordinal));
            if (resource == null) return null;
            using (var stream = assembly.GetManifestResourceStream(resource))
            using (var reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd();
        }

        public static IDictionary<string, object> ConfigShow()
        {
            var userPath = UserDefaults.Path;
            var user = Read(userPath);
            user.Remove("version");
            var set = user.ContainsKey(QuickKeySetting);
            return new Dictionary<string, object> {
                { "user_defaults", new Dictionary<string, object>
                    {
                        { "path", userPath },
                        { "status", File.Exists(userPath) ? "ok" : "missing" },
                        { "overrides", user },
                    } },
                { "settings", new Dictionary<string, object>
                    {
                        { QuickKeySetting, new Dictionary<string, object> { { "value", set ? user[QuickKeySetting] : QuickKey.DefaultText }, { "source", set ? "user" : "code" } } },
                    } },
            };
        }

        public static IDictionary<string, object> ConfigChange(CliOptions o, bool unset)
        {
            var args = o.Arguments;
            if (args.Count < (unset ? 1 : 2))
                throw Refuse("config", unset ? "unset needs a key" : "set needs a key and value");
            var key = args[0];
            if (key != QuickKeySetting)
                throw Refuse("config", "unknown setting: " + key + ". The one setting is " + QuickKeySetting);
            var path = UserDefaults.Path;
            var data = Read(path);
            var changed = unset && data.Remove(key);
            string note = null;
            if (!unset)
            {
                var parsed = QuickKey.Parse(args[1]) ?? throw Refuse("config", "invalid value for quick_key");
                if (parsed.Text == QuickKey.DefaultText)
                {
                    data.Remove(key);
                    note = "equal to the code default; no override stored";
                }
                else data[key] = parsed.Text;
                changed = true;
            }
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            data["version"] = 1L;
            File.WriteAllText(path, Json.Pretty(data) + "\n", new UTF8Encoding(false));
            var result = new Dictionary<string, object> { { "key", key } };
            if (unset) { result["removed"] = changed; if (!changed) result["note"] = "no override"; }
            else if (note != null) { result["value"] = null; result["note"] = note; }
            else result["value"] = data[key];
            return result;
        }

        static Dictionary<string, object> Read(string path)
        {
            try
            {
                return Json.Parse(File.ReadAllText(path)) as Dictionary<string, object>
                    ?? new Dictionary<string, object>();
            }
            catch (JsonException) { return new Dictionary<string, object>(); }
            catch (IOException) { return new Dictionary<string, object>(); }
            catch (UnauthorizedAccessException) { return new Dictionary<string, object>(); }
        }

        static CliFailure Refuse(string command, string message) => new CliFailure(command, "refused", message, "cts " + command + " --help", 1);
    }
}
