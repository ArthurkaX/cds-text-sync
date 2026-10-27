using System;
using System.Collections.Generic;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;
using static Cts.Agent.Palette;

namespace Cts.Agent
{
    internal sealed partial class FsmView
    {
        //: Between two reads, and after a read that failed.
        const int ReadEveryMs = 250;
        const int RetryAfterMs = 2000;

        //: vars.read in this agent, called off the window's thread.
        readonly Func<IList<string>, IDictionary<string, object>> _read;
        readonly Timer _tick = new Timer();
        Panel _watchBar;
        ComboBox _watch;
        Button _live;
        bool _living;
        bool _reading;
        //: The state last read and since when the window has seen it.
        string _state;
        DateTime _since;

        // The path to read: one per instance `cts fsm` found, or typed.
        Control WatchBar()
        {
            _watch = new ComboBox { Dock = DockStyle.Fill, DropDownStyle = ComboBoxStyle.DropDown, BackColor = Bar, ForeColor = Ink, FlatStyle = FlatStyle.Flat, Font = Mono };
            _watch.TextChanged += (s, e) => Restart();
            var label = new Label { Text = "read", Dock = DockStyle.Left, Width = 44, ForeColor = Muted, Font = Mono, TextAlign = ContentAlignment.MiddleLeft, Padding = new Padding(6, 0, 0, 0) };
            _watchBar = new Panel { Dock = DockStyle.Top, Height = 26, Visible = false, Padding = new Padding(0, 1, 6, 1) };
            _watchBar.Controls.Add(_watch);
            _watchBar.Controls.Add(label);
            _tick.Tick += (s, e) => Poll();
            return _watchBar;
        }

        // The chosen machine's instances to choose from; a typed path stays
        // when the new machine has it too.
        void Watch(Row row)
        {
            var typed = _watch.Text;
            _watch.BeginUpdate();
            _watch.Items.Clear();
            if (row != null) foreach (var path in row.Machine.Watch) _watch.Items.Add(path);
            _watch.EndUpdate();
            if (row != null && row.Machine.Watch.Contains(typed)) _watch.Text = typed;
            else if (_watch.Items.Count > 0) _watch.SelectedIndex = 0;
            else _watch.Text = "";
            Restart();
        }

        void ToggleLive()
        {
            _living = !_living;
            _live.Text = _living ? "Stop &live" : "&Live";
            _watchBar.Visible = _living;
            Restart();
            if (!_living) Say("live view off", Muted);
        }

        // A new machine or path: the state read so far says nothing about it.
        void Restart()
        {
            _tick.Stop();
            _state = null;
            _chart.Live(null, new List<int>());
            if (_living) Poll();
        }

        void Poll()
        {
            _tick.Stop();
            if (!_living || _reading) return;
            var row = Selected();
            var path = _watch.Text.Trim();
            if (row == null || path.Length == 0)
            {
                Say(row == null ? "live: choose a machine" : "live: no instance of " + row.Owner.Label + " found; type the path to read, as cts read takes it", Muted);
                return;
            }
            _reading = true;
            Task.Run(() =>
            {
                string value = null, failure;
                try { value = FsmMap.LiveValue(_read(new[] { path }), out failure); }
                catch (ProtocolException e) { failure = e.Message; }
                Later(() => { _reading = false; Seen(row, path, value, failure); });
            });
        }

        void Seen(Row row, string path, string value, string failure)
        {
            if (!_living) return;
            if (row != Selected() || path != _watch.Text.Trim()) { Poll(); return; }
            if (value == null)
            {
                Say("live " + path + ": " + failure, Bad);
                _state = null;
                _chart.Live(null, new List<int>());
                _tick.Interval = RetryAfterMs;
                _tick.Start();
                return;
            }
            var state = FsmMap.StateOf(row.Machine, value);
            if (state != _state)
            {
                _chart.Live(state, _state != null && state != null ? FsmMap.Taken(row.Machine, _state, state) : new List<int>());
                _state = state;
                _since = DateTime.Now;
            }
            Say("live " + path + " = " + value + (state == null ? ", no step has this value"
                : ", seen in this step " + (int)(DateTime.Now - _since).TotalSeconds + " s"), state == null ? Muted : Good);
            _tick.Interval = ReadEveryMs;
            _tick.Start();
        }
    }
}
