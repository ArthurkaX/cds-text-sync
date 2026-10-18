// `messages.read`: the messages of one of the IDE's message categories
// (`cts read-log`), as the Messages view shows them, and the categories there
// are.  `clear` empties the category after the read.  No project is needed:
// the message storage is the IDE's.  The deny list key is `read_log`.
using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        internal Dictionary<string, object> ReadMessages(string requested, long last, bool clear)
        {
            RequireKey(DenyRules.ReadLog);
            var storageIface = FindType("_3S.CoDeSys.Core.Messages.IMessageStorage");
            var storage = SystemInstance(storageIface.FullName);
            var categoryIface = FindType("_3S.CoDeSys.Core.Messages.IMessageCategory");
            var categories = ((Array)Prop(storageIface, storage, "Categories")).Cast<object>().ToList();
            var available = categories.Select(c => new Dictionary<string, object>
            {
                { "guid", CategoryGuid(c) == Guid.Empty ? "" : CategoryGuid(c).ToString() },
                { "description", Convert.ToString(Prop(categoryIface, c, "Text")) },
            }).ToList();
            var chosen = MessageCategories.Pick(requested, available);
            var index = available.IndexOf(chosen);

            var texts = new List<string>();
            if (index >= 0)
            {
                var category = categories[index];
                var read = NeedMethod(storageIface, "GetMessages", new[] { categoryIface }, "IMessageStorage.GetMessages is not present in this IDE");
                var messageIface = FindType("_3S.CoDeSys.Core.Messages.IMessage");
                foreach (var message in (Array)read.Invoke(storage, new[] { category }))
                    texts.Add(Convert.ToString(Prop(messageIface, message, "Text")));
                if (clear) storageIface.GetMethod("ClearMessages").Invoke(storage, new[] { category });
            }
            var messages = MessageCategories.Last(texts, last);
            return new Dictionary<string, object>
            {
                { "category", chosen },
                { "count", messages.Count },
                { "messages", messages.Cast<object>().ToList() },
                { "available_categories", available.Cast<object>().ToList() },
            };
        }

        // The GUID a category's class declares (TypeGuidAttribute), the one
        // the scripting API names it by; Empty for a class that declares none.
        static Guid CategoryGuid(object category)
        {
            var tag = category.GetType().GetCustomAttributes(true)
                .FirstOrDefault(a => a.GetType().FullName == "_3S.CoDeSys.Core.Components.TypeGuidAttribute");
            return tag == null ? Guid.Empty : (Guid)tag.GetType().GetProperty("Guid").GetValue(tag, null);
        }
    }
}
