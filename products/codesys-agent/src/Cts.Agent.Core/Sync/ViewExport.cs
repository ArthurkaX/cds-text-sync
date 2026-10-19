using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Security.Cryptography;
using System.Xml.Linq;
using Cts.Agent;
using static Cts.Agent.JsonMap;

namespace Cts.Sync
{
    internal sealed class ExportedTextPart
    {
        internal IList<string> Path;
        internal string Kind, Declaration, Implementation;
    }

    public static partial class ViewExport
    {
        // The `.xml` that `cts export` writes for one snapshot entry; a text
        // list's *rowless*, its rows being in its `.csv`.
        internal static byte[] NativeBytes(XElement entry, bool rowless)
        {
            return new UTF8Encoding(false).GetBytes(CanonicalXml(rowless ? TextListRows.Without(entry) : entry));
        }

        // The `.xml` beside a text object's `.st`: its settings, without the text.
        internal static byte[] SettingsBytes(XElement entry)
        {
            return new UTF8Encoding(false).GetBytes(ExternalizedXml(entry));
        }

        // The `.csv` of a text list, or of an alarm group with its *messages*.
        internal static byte[] CsvBytes(XElement entry, XElement messages)
        {
            var csv = Field(entry, "Alarms") != null ? AlarmItemsCsv(entry, messages) : TextListCsv(entry);
            return csv == null ? null : new UTF8Encoding(false).GetBytes(csv);
        }

        // The guid of the text list an alarm group's messages are rows of.
        internal static string AlarmMessagesGuid(XElement group) => Field(Field(group, "TextListReference"), "Guid")?.Value.Trim().Trim('{', '}').ToLowerInvariant();

        static XElement Field(XElement parent, string name) => parent?.Descendants().FirstOrDefault(e => (string)e.Attribute("Name") == name);

        internal sealed class TextPart
        {
            internal ProjectNode Node;
            internal string Kind, Declaration, Implementation;
            internal List<TextPart> Accessors = new List<TextPart>();
        }

        // *stamps* as taken before the view was read; a file changed since stays as it is.
        internal static ExportResult Write(string snapshotPath, string projectRoot, IDictionary<string, object> known, IList<ExportedTextPart> textParts = null, ViewStamps stamps = null)
        {
            var view = ViewFolder.Of(Path.GetFullPath(projectRoot));
            var target = new FolderViewRenderTarget(view, projectRoot, stamps ?? ViewStamps.Take(view));
            var result = WriteTo(snapshotPath, projectRoot, known, target, textParts);
            result.Ignored = target.Ignored;
            return result;
        }

        internal static ExportResult WriteTo(string snapshotPath, string projectRoot, IDictionary<string, object> known, IViewRenderTarget target, IList<ExportedTextPart> textParts = null)
        {
            return WriteModel(SnapshotReader.Read(snapshotPath), projectRoot, known, target, textParts, null);
        }

        internal static ExportResult WriteSubset(ProjectModel model, string projectRoot, IViewRenderTarget target, IEnumerable<string> guids)
        {
            return WriteModel(model, projectRoot, null, target, null, new HashSet<string>(guids, StringComparer.OrdinalIgnoreCase));
        }

        static ExportResult WriteModel(ProjectModel model, string projectRoot, IDictionary<string, object> known, IViewRenderTarget target, IList<ExportedTextPart> textParts, ISet<string> onlyGuids)
        {
            var root = Path.GetFullPath(projectRoot);
            var result = new ExportResult { Model = model };
            var selected = new Dictionary<string, TextPart>();
            var unread = new List<string>();
            foreach (var node in model.Nodes.Values)
            {
                if (node.Entry == null || (onlyGuids != null && !onlyGuids.Contains(node.Guid))) continue;
                var kind = TypeKinds.All.Kind(node.Type);
                if (kind == null) continue;
                var projection = TypeKinds.All.Projections.FirstOrDefault(p => ProjectionApplies(p, kind));
                if (projection == null || !string.Equals(Text(projection, "format"), "st", StringComparison.OrdinalIgnoreCase)) continue;
                if (Graphical(model, node)) continue;
                var sections = TextSections(node.Entry);
                if (sections.Count == 0) continue;
                var declaration = sections.FirstOrDefault(s => s.Kind == "declaration")?.Declaration ?? "";
                var implementation = sections.FirstOrDefault(s => s.Kind == "implementation")?.Implementation;
                if (declaration.Trim().Length == 0 && Declares.Contains(kind)) unread.Add(node.Name);
                var partKind = KindOf(node.Name, declaration, kind);
                if (partKind.Length == 0) continue;
                var pragma = CtsPragma(node, StPragma.Read(node.Entry));
                if (pragma != null) declaration = pragma + (declaration.Length == 0 ? "" : "\n" + declaration);
                selected[node.Guid] = new TextPart { Node = node, Kind = partKind, Declaration = declaration, Implementation = implementation };
            }
            if (unread.Count > 0) throw new InvalidOperationException(Unread(unread));
            if (textParts != null)
                foreach (var part in selected.Values)
                    textParts.Add(new ExportedTextPart { Path = part.Node.IdeParts(), Kind = part.Kind, Declaration = part.Declaration, Implementation = part.Implementation });
            var byPath = selected.Values.ToDictionary(p => PathKey(p.Node.Parts(model)), p => p, StringComparer.OrdinalIgnoreCase);
            var members = new Dictionary<string, List<TextPart>>(StringComparer.OrdinalIgnoreCase);
            var owners = new List<TextPart>();
            foreach (var part in selected.Values)
            {
                var natural = part.Node.Parts(model);
                var parent = natural.Count > 1 ? PathKey(natural.Take(natural.Count - 1)) : "";
                TextPart owner = null;
                var hasParent = part.Node.ParentGuid != null && selected.TryGetValue(part.Node.ParentGuid, out owner);
                if (IsMember(part.Kind) && (hasParent || byPath.TryGetValue(parent, out owner)))
                {
                    var key = PathKey(owner.Node.Parts(model));
                    if (!members.ContainsKey(key)) members[key] = new List<TextPart>();
                    members[key].Add(part);
                }
                else owners.Add(part);
            }
            var textGuids = new HashSet<string>(selected.Keys, StringComparer.OrdinalIgnoreCase);
            var selectedTextParts = selected.Values.ToList();
            foreach (var owner in owners)
            {
                var key = PathKey(owner.Node.Parts(model));
                var attached = members.ContainsKey(key) ? members[key] : new List<TextPart>();
                foreach (var prop in attached.Where(p => p.Kind == "PROPERTY"))
                {
                    var propertyPath = PathKey(prop.Node.Parts(model));
                    if (members.ContainsKey(propertyPath)) prop.Accessors = members[propertyPath];
                }
                var content = Join(owner, attached.Where(p => p.Kind != "GET" && p.Kind != "SET"));
                var rel = string.Join("/", owner.Node.Parts(model)) + ".st";
                Emit(target, rel, content, result, owner.Node.Guid);
                foreach (var member in attached) selected.Remove(member.Node.Guid);
            }
            foreach (var part in selectedTextParts)
            {
                if (!TextSettings.Outside(part.Node.Entry)) continue;
                Emit(target, model.XmlPath(part.Node), ExternalizedXml(part.Node.Entry), result, part.Node.Guid);
            }
            foreach (var node in model.Nodes.Values)
            {
                if (node.Entry == null || (onlyGuids != null && !onlyGuids.Contains(node.Guid))) continue;
                if (textGuids.Contains(node.Guid)) continue;
                var options = TypeKinds.All.Projections.Where(p => ProjectionApplies(p, TypeKinds.All.Kind(node.Type))).ToList();
                foreach (var projection in options.Where(p => string.Equals(Text(p, "format"), "csv", StringComparison.OrdinalIgnoreCase)))
                {
                    var extractor = Text(projection, "extractor");
                    if (extractor != "alarm_items_csv" && AlarmGroupOf(model, node) != null) continue;
                    var csv = extractor == "alarm_items_csv" ? AlarmItemsCsv(node.Entry, AlarmMessages(model, node)?.Entry) : TextListCsv(node.Entry);
                    if (csv != null) Emit(target, ReplaceExtension(model.XmlPath(node), ".csv"), csv, result, node.Guid);
                }
                if (model.CollapsedParent(node) != null && options.Count == 0) continue;
                var xmlPath = model.XmlPath(node);
                var stamp = MetaTimestamp(node.Entry);
                if (stamp.HasValue && Known(known, node.Guid, stamp.Value, xmlPath, target))
                {
                    target.Keep(xmlPath);
                    result.Natives.Add(new NativeExport { Guid = node.Guid, Timestamp = stamp.Value, Path = xmlPath });
                    continue;
                }
                // A text list with a .csv of its own keeps its rows only there.
                var rowless = TextListRows.IsTextList(node.Type) && AlarmGroupOf(model, node) == null;
                Emit(target, xmlPath, CanonicalXml(rowless ? TextListRows.Without(node.Entry) : node.Entry), result, node.Guid);
                if (stamp.HasValue) result.Natives.Add(new NativeExport { Guid = node.Guid, Timestamp = stamp.Value, Path = xmlPath });
            }
            WriteDirectories(model, target, textGuids, result);
            foreach (var orphan in target.KeptOrphans()) result.KeptOrphans.Add(orphan);
            return result;
        }

        static bool Known(IDictionary<string, object> known, string guid, long stamp, string path, IViewRenderTarget target)
        {
            object raw;
            if (known == null || !known.TryGetValue((guid ?? "").Trim('{', '}').ToLowerInvariant(), out raw) || !(raw is IList<object> pair) || pair.Count != 2) return false;
            if (Convert.ToInt64(pair[0], System.Globalization.CultureInfo.InvariantCulture) != stamp) return false;
            return target.HasBlob(path, Convert.ToString(pair[1]));
        }

        // The id git gives these bytes as a blob; a repository made with
        // --object-format=sha256 passes its format.
        public static string BlobId(byte[] bytes, string format = "sha1")
        {
            var header = Encoding.ASCII.GetBytes("blob " + bytes.Length.ToString(System.Globalization.CultureInfo.InvariantCulture) + "\0");
            var input = new byte[header.Length + bytes.Length];
            Buffer.BlockCopy(header, 0, input, 0, header.Length);
            Buffer.BlockCopy(bytes, 0, input, header.Length, bytes.Length);
            using (var hash = format == "sha256" ? (HashAlgorithm)SHA256.Create() : SHA1.Create()) return string.Concat(hash.ComputeHash(input).Select(b => b.ToString("x2", System.Globalization.CultureInfo.InvariantCulture)));
        }

        static long? MetaTimestamp(XElement entry)
        {
            var meta = entry.Elements().FirstOrDefault(e => (string)e.Attribute("Name") == "MetaObject");
            var stamp = meta?.Elements().FirstOrDefault(e => (string)e.Attribute("Name") == "Timestamp");
            return long.TryParse(stamp?.Value, out var value) ? (long?)value : null;
        }

        static bool ProjectionApplies(IDictionary<string, object> p, string kind)
        {
            if (kind == null) return false;
            object kinds;
            var allowed = p.TryGetValue("kinds", out kinds) && kinds is IList<object> ? ((IList<object>)kinds).Select(Convert.ToString).ToList() : new List<string> { Text(p, "kind") };
            return allowed.Contains(kind);
        }

        // An alarm group's messages are the rows of the text list the IDE makes
        // for it, of its name, beside it: the group's .csv carries them, and
        // that list has no .csv of its own.
        static ProjectNode AlarmMessages(ProjectModel model, ProjectNode group) => Twin(model, group, "textlist");

        static ProjectNode AlarmGroupOf(ProjectModel model, ProjectNode list) =>
            TypeKinds.All.Kind(list.Type) == "textlist" ? Twin(model, list, "alarm_config_item") : null;

        static ProjectNode Twin(ProjectModel model, ProjectNode node, string kind) => model.Nodes.Values.FirstOrDefault(other => other.Guid != node.Guid
            && string.Equals(other.ParentGuid, node.ParentGuid, StringComparison.OrdinalIgnoreCase)
            && string.Equals(other.Name, node.Name, StringComparison.OrdinalIgnoreCase) && TypeKinds.All.Kind(other.Type) == kind);
        // A graphical POU (CFC, FBD, LD, SFC) is an .xml, and so is each of its
        // members, ST ones too, beside it; a graphical member of an ST owner
        // is an .xml beside the owner's .st.
        static bool Graphical(ProjectModel model, ProjectNode node)
        {
            for (var item = node; item != null; )
            {
                if (item.Metadata.ContainsKey("graphical")) return true;
                item = IsMemberType(TypeKinds.All.Kind(item.Type)) && item.ParentGuid != null && model.Nodes.TryGetValue(item.ParentGuid, out var parent) ? parent : null;
            }
            return false;
        }
        static readonly HashSet<string> MemberKinds = new HashSet<string>(StringComparer.Ordinal) { "METHOD", "PROPERTY", "ACTION", "GET", "SET" };
        static readonly HashSet<string> MemberTypes = new HashSet<string>(StringComparer.Ordinal) { "method", "action", "property", "property_accessor", "itf_method" };
        static bool IsMember(string kind) { return MemberKinds.Contains(kind); }
        static bool IsMemberType(string kind) { return MemberTypes.Contains(kind); }
        static string PathKey(IEnumerable<string> parts) { return string.Join("/", parts); }

        static List<TextPart> TextSections(XElement entry)
        {
            var result = new List<TextPart>();
            foreach (var e in entry.DescendantsAndSelf())
            {
                var name = (string)e.Attribute("Name");
                if (name != "TextBlobForSerialisation" && name != "TextLines") continue;
                var parentNames = e.Ancestors().Select(a => (string)a.Attribute("Name") ?? "").ToList();
                var role = parentNames.Any(n => n.Equals("Interface", StringComparison.OrdinalIgnoreCase) || n.Equals("Declaration", StringComparison.OrdinalIgnoreCase)) ? "declaration" : parentNames.Contains("Implementation") ? "implementation" : "section";
                var value = name == "TextLines" ? string.Join("\n", e.Elements().Select(line => line.Elements().FirstOrDefault(x => (string)x.Attribute("Name") == "Text")?.Value ?? "")) : e.Value;
                var part = result.FirstOrDefault(p => p.Kind == role);
                if (part == null) { part = new TextPart { Kind = role }; result.Add(part); }
                if (role == "declaration") part.Declaration = value; else if (role == "implementation") part.Implementation = value;
                else { if (part.Declaration == null) part.Declaration = value; else part.Implementation = value; }
            }
            return result.OrderBy(p => p.Kind == "declaration" ? 0 : p.Kind == "implementation" ? 1 : 2).ToList();
        }

        // The kinds whose text always starts with a declaration (FUNCTION_BLOCK
        // X, TYPE X :, VAR_GLOBAL): one that reads empty is an object CODESYS
        // did not load, and writing it would empty its file.
        static readonly HashSet<string> Declares = new HashSet<string>(StringComparer.Ordinal)
            { "pou", "dut", "gvl", "persistent_gvl", "task_local_gvl", "method", "itf_method", "property", "interface" };

        static string Unread(IList<string> names)
        {
            return names.Count + " object(s) read empty in the IDE (" + string.Join(", ", names.Take(5))
                + (names.Count > 5 ? ", ..." : "") + "): CODESYS did not load them -- a project saved by a newer "
                + "CODESYS, or a missing library or device description ([incomplete] in its tree). Nothing was written; "
                + "open the project in the CODESYS that saved it";
        }

        static string KindOf(string name, string declaration, string typeKind)
        {
            foreach (var line in (declaration ?? "").Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
            {
                var trimmed = line.TrimStart();
                foreach (var keyword in new[] { "FUNCTION_BLOCK", "PROGRAM", "FUNCTION", "METHOD", "PROPERTY", "INTERFACE" })
                    if (trimmed.StartsWith(keyword, StringComparison.OrdinalIgnoreCase) && (trimmed.Length == keyword.Length || char.IsWhiteSpace(trimmed[keyword.Length]))) return keyword;
            }
            if (typeKind == "gvl" || typeKind == "persistent_gvl" || typeKind == "task_local_gvl") return "VAR_GLOBAL";
            if (typeKind == "dut") return "TYPE";
            if (typeKind == "action") return "ACTION";
            if (typeKind == "property_accessor") return (name ?? "").ToUpperInvariant();
            if (typeKind == "method" || typeKind == "itf_method") return "METHOD";
            return "";
        }
        internal static string Join(TextPart owner, IEnumerable<TextPart> members)
        {
            var blocks = new List<string> { Block(owner.Declaration, owner.Implementation, End(owner.Kind), null) };
            foreach (var member in members)
            {
                if (member.Kind == "ACTION")
                {
                    var heading = (member.Declaration ?? "").Length == 0 ? "" : member.Declaration.Trim() + "\n";
                    blocks.Add(Block(heading + "ACTION " + member.Node.Name + ":", null, "END_ACTION", member.Implementation));
                }
                else if (member.Kind == "PROPERTY")
                {
                    var propertyDeclaration = StText.Lf(member.Declaration ?? "");
                    var lines = new List<string> { propertyDeclaration.TrimEnd() };
                    foreach (var accessor in member.Accessors) lines.Add(accessor.Kind + "\n" + Block(accessor.Declaration, accessor.Implementation, "END_" + accessor.Kind, null).TrimStart('\n'));
                    lines.Add("END_PROPERTY"); blocks.Add(StripBlankEdges(string.Join("\n", lines.Where(s => s.Length > 0))));
                }
                else blocks.Add(Block(member.Declaration, member.Implementation, End(member.Kind), null));
            }
            return string.Join("\n\n", blocks) + "\n";
        }
        static string Block(string declaration, string implementation, string end, string body)
        {
            var parts = new List<string>();
            if (!string.IsNullOrEmpty(declaration))
            {
                parts.Add(StText.Lf(declaration).TrimEnd());
            }
            if (body != null) { if (body.Trim().Length > 0) parts.Add(TrimEdges(body)); }
            else if (!string.IsNullOrEmpty(implementation)) { parts.Add(StPragma.ImplementationMarker); parts.Add(TrimEdges(implementation)); }
            if (!string.IsNullOrEmpty(end)) parts.Add(end);
            return StripBlankEdges(string.Join("\n", parts));
        }
        // The text between a block's header and its END keyword: the IDE's,
        // without blank lines at its start and whitespace at its end; the
        // first line keeps its indent.
        static string TrimEdges(string text)
        {
            var lines = StText.Lf(text).TrimEnd().Split('\n').ToList();
            while (lines.Count > 0 && lines[0].Trim().Length == 0) lines.RemoveAt(0);
            return string.Join("\n", lines);
        }
        static string StripBlankEdges(string text)
        {
            var lines = (text ?? "").Split('\n').ToList();
            while (lines.Count > 0 && lines[0].Length == 0) lines.RemoveAt(0);
            while (lines.Count > 0 && lines[lines.Count - 1].Length == 0) lines.RemoveAt(lines.Count - 1);
            return string.Join("\n", lines);
        }
        static string End(string kind) { return StPragma.EndForKind(kind); }
        static string CtsPragma(ProjectNode node, IDictionary<string, string> settings)
        {
            var kind = TypeKinds.All.Kind(node.Type);
            return StPragma.Format(TypeKinds.All.IsAmbiguous(kind, node.Type) ? node.Type : null, settings);
        }
        static string ReplaceExtension(string path, string extension) { return Path.ChangeExtension(path, extension).Replace('\\', '/'); }
        static void Emit(IViewRenderTarget target, string relative, string content, ExportResult result, string guid)
        {
            if (PathSafety.SafePath(Path.GetTempPath(), relative) == null) return;
            target.Write(relative, new UTF8Encoding(false).GetBytes(content ?? ""));
            if (!result.GuidFiles.TryGetValue(guid, out var paths)) result.GuidFiles[guid] = paths = new List<string>();
            if (!paths.Contains(relative, StringComparer.OrdinalIgnoreCase)) paths.Add(relative);
        }
        static void WriteDirectories(ProjectModel model, IViewRenderTarget target, HashSet<string> textGuids, ExportResult result)
        {
            foreach (var node in model.Nodes.Values.Where(n => n.Entry != null && model.HasOutputChildren(n) && model.CollapsedParent(n) == null && !textGuids.Contains(n.Guid)))
            {
                var parts = node.Parts(model);
                var path = string.Join("/", parts.Concat(new[] { ".cds-object.xml" }));
                Emit(target, path, CanonicalXml(node.Entry), result, node.Guid);
                var stamp = MetaTimestamp(node.Entry);
                if (stamp.HasValue) result.Natives.Add(new NativeExport { Guid = node.Guid, Timestamp = stamp.Value, Path = path });
            }
        }
    }
}
