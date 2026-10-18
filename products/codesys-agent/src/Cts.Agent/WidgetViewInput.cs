using System.Drawing;
using System.Windows.Forms;

namespace Cts.Agent
{
    // The keys and the mouse: digits, arrows, Enter, Esc, hover and click.
    internal sealed partial class WidgetView
    {
        protected override void OnKeyPress(KeyPressEventArgs e)
        {
            // While a question is asked the keys are the answer's.
            if (_asking != null) return;
            var key = e.KeyChar;
            if (!Later(() => Choose(WidgetMenu.ForKey(_items, key)))) Choose(WidgetMenu.ForKey(_items, key));
            e.Handled = true;
        }

        // Esc, which the agent's keyboard hook hands over before the IDE
        // sees it: cancels a question, else goes back up a page, else closes.
        public void Escape()
        {
            if (Later(Escape)) return;
            if (_asking != null) { StopAsking(); Idle(); }
            else if (!Running && !Up()) Close();
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            return Key(keyData) || base.ProcessCmdKey(ref msg, keyData);
        }

        // A key the window takes itself; false for one the controls get.
        bool Key(Keys keyData)
        {
            if (keyData == Keys.Escape) { Escape(); return true; }
            if (_asking == null && Later(() => Key(keyData))) return true;
            if (keyData == (Keys.Control | Keys.C) && CopyShown && _asking == null) { CopyAsked?.Invoke(); return true; }
            if (_asking != null)
            {
                if (keyData == Keys.Enter) { Answer(); return true; }
                if (keyData == Keys.F4 && _asking.Picks != null) { Browse(); return true; }
                return false;
            }
            // Shift with a digit: the row's run without a question.  The key is
            // taken here, before the layout turns it into a character (!).
            var code = keyData & Keys.KeyCode;
            if ((keyData & Keys.Modifiers) == Keys.Shift && code >= Keys.D0 && code <= Keys.D9)
            {
                var item = WidgetMenu.ForKey(_items, (char)('0' + (code - Keys.D0)));
                if (item?.Forced == null) return false;
                Choose(item, true);
                return true;
            }
            switch (keyData)
            {
                case Keys.Left:
                    if (!Running) Up();
                    return true;
                case Keys.Right:
                    if (_items.Count > 0 && _items[_selected].Opens != WidgetPage.None) Choose(_items[_selected]);
                    return true;
                case Keys.Space:
                    if (_items.Count > 0 && _items[_selected].Toggles != null) Choose(_items[_selected]);
                    return true;
                case Keys.Enter: if (_items.Count > 0) Choose(_items[_selected]); return true;
                case Keys.PageUp: ScrollFooter(-_footerShown); return true;
                case Keys.PageDown: ScrollFooter(_footerShown); return true;
                case Keys.Up: Step(-1); return true;
                case Keys.Down: Step(1); return true;
            }
            return false;
        }

        void Step(int step)
        {
            if (_items.Count == 0) return;
            _selected = (_selected + step + _items.Count) % _items.Count;
            Invalidate();
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            if (e.Location == _mouse) return;
            _mouse = e.Location;
            if (_asking != null && _asking.Picks != null) Invalidate(BrowseRect());
            if (CopyShown) Invalidate(CopyRect());
            var row = RowAt(e.Location);
            if (row >= 0 && row != _selected) { _selected = row; Invalidate(); }
        }

        protected override void OnMouseClick(MouseEventArgs e)
        {
            if (_asking != null && _asking.Picks != null && BrowseRect().Contains(e.Location)) { Browse(); return; }
            if (CopyShown && CopyRect().Contains(e.Location)) { CopyAsked?.Invoke(); return; }
            var row = RowAt(e.Location);
            if (row >= 0) Choose(_items[row], ModifierKeys == Keys.Shift);
        }

        int RowAt(Point point)
        {
            var row = (point.Y - HeaderHeight) / RowHeight;
            return point.Y >= HeaderHeight && row < _items.Count ? row : -1;
        }
    }
}
