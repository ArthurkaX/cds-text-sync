#if DEBUG
using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows.Forms;

namespace Cts.Agent
{
    internal sealed partial class WidgetView
    {
        // widget.drive's hands: what a typed key, a named key, a typed line
        // and a click on Copy do, and what the window shows.
        internal void Press(char key)
        {
            if (_asking != null) _answer.SelectedText = key.ToString();
            else if (!Later(() => Press(key))) Choose(WidgetMenu.ForKey(_items, key));
        }

        internal void Press(Keys key)
        {
            if (key == Keys.Back && _asking != null && _answer.Text.Length > 0) _answer.Text = _answer.Text.Substring(0, _answer.Text.Length - 1);
            else Key(key);
        }

        internal void Type(string text)
        {
            if (_asking == null) throw new InvalidOperationException("type: needs a row that asks for a line, and none is asked");
            // As typing does: over what is selected (the value the line opened with).
            _answer.SelectedText = text;
        }

        internal void ClickCopy()
        {
            if (!CopyShown) throw new InvalidOperationException("copy: no failure is shown");
            CopyAsked?.Invoke();
        }

        internal IDictionary<string, object> Snapshot()
        {
            var rows = new List<object>();
            for (var i = 0; i < _items.Count; i++)
            {
                var item = _items[i];
                rows.Add(new Dictionary<string, object>
                {
                    { "key", item.Key == '\0' ? "" : item.Key.ToString() },
                    { "label", item.Label },
                    { "hint", item.Hint },
                    { "enabled", Blocked(item) == null },
                    { "blocked", Blocked(item) },
                    { "selected", i == _selected },
                    { "current", item.Current },
                });
            }
            return new Dictionary<string, object>
            {
                { "open", true },
                { "branch", _branch },
                { "commit", _commit },
                { "state", _state },
                { "place", _place },
                { "online", _online },
                { "level", _inList ? _level : 0 },
                { "rows", rows },
                { "footer", _footer },
                { "ok", _ok },
                { "running", Running },
                { "busy", _busy },
                { "asking", _asking?.Asks },
                { "typed", _asking != null ? _answer.Text : null },
                { "copy", CopyShown },
                { "trail", _trail.Cast<object>().ToList() },
            };
        }
    }
}
#endif
