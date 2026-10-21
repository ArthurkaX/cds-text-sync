// Two code panes side by side (the format window, the conflict window): a
// text on the left, another on the right, the lines that differ marked, and
// either pane's scroll followed by the other -- up and down to the line
// beside it (FmtDiff.LeftOf), left and right by the same offset.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;

namespace Cts.Agent
{
    internal sealed class PanePair
    {
        const int EM_GETFIRSTVISIBLELINE = 0x00CE;
        const int EM_LINESCROLL = 0x00B6;
        const int EM_GETSCROLLPOS = 0x04DD;
        const int EM_SETSCROLLPOS = 0x04DE;

        readonly RichTextBox _left;
        readonly RichTextBox _right;
        //: How the shown texts' lines pair up; null while the panes are empty.
        FmtDiff _diff;
        bool _scrolling;

        internal PanePair(RichTextBox left, RichTextBox right)
        {
            _left = left;
            _right = right;
            left.VScroll += (s, e) => Follow(left, right);
            right.VScroll += (s, e) => Follow(right, left);
            left.HScroll += (s, e) => Across(left, right);
            right.HScroll += (s, e) => Across(right, left);
        }

        // *left* and *right* in the panes, the lines that differ marked in
        // *leftMark* and *rightMark*; how they pair up.
        internal FmtDiff Show(string left, string right, Color leftMark, Color rightMark)
        {
            CodeText.Show(_left, left);
            CodeText.Show(_right, right);
            _diff = FmtReview.Changed(left, right);
            Mark(_left, _diff.Left, leftMark);
            Mark(_right, _diff.Right, rightMark);
            return _diff;
        }

        internal void Clear()
        {
            _diff = null;
            _left.Text = "";
            _right.Text = "";
        }

        static void Mark(RichTextBox box, IEnumerable<int> lines, Color color)
        {
            var text = box.Lines;
            foreach (var line in lines)
            {
                var start = box.GetFirstCharIndexFromLine(line);
                if (start < 0) continue;
                box.Select(start, text[line].Length + 1);
                box.SelectionBackColor = color;
            }
            box.Select(0, 0);
        }

        // *line* of the right pane (or the left one) a few lines below the
        // top, the other pane beside it.
        internal void ScrollNear(bool right, int line)
        {
            var pane = right ? _right : _left;
            ScrollTo(pane, Math.Max(0, line - 3));
            Follow(pane, right ? _left : _right);
        }

        // *to* follows *from* up or down: a right line maps to the left line beside it.
        void Follow(RichTextBox from, RichTextBox to)
        {
            if (_scrolling || _diff == null) return;
            _scrolling = true;
            try
            {
                var top = FirstVisible(from);
                var map = _diff.LeftOf;
                var target = from == _right
                    ? (top < map.Length ? map[top] : top)
                    : Math.Max(0, Array.FindIndex(map, left => left >= top));
                ScrollTo(to, target);
            }
            finally { _scrolling = false; }
        }

        // *to* follows *from* left or right, keeping its own place up or down.
        void Across(RichTextBox from, RichTextBox to)
        {
            if (_scrolling) return;
            _scrolling = true;
            try
            {
                var source = new Point();
                var target = new Point();
                Win32.SendMessage(from.Handle, EM_GETSCROLLPOS, IntPtr.Zero, ref source);
                Win32.SendMessage(to.Handle, EM_GETSCROLLPOS, IntPtr.Zero, ref target);
                target.X = source.X;
                Win32.SendMessage(to.Handle, EM_SETSCROLLPOS, IntPtr.Zero, ref target);
            }
            finally { _scrolling = false; }
        }

        static int FirstVisible(RichTextBox box)
        {
            return (int)Win32.SendMessage(box.Handle, EM_GETFIRSTVISIBLELINE, IntPtr.Zero, IntPtr.Zero);
        }

        static void ScrollTo(RichTextBox box, int line)
        {
            Win32.SendMessage(box.Handle, EM_LINESCROLL, IntPtr.Zero, (IntPtr)(line - FirstVisible(box)));
        }
    }
}
