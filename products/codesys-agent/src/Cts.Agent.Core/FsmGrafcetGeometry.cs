using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    internal static partial class FsmGrafcet
    {
        // The geometry: column widths, the priority block, the steps on their rows and the page's extent.
        sealed partial class Grafcet
        {
            void MeasureColumns()
            {
                foreach (var label in _order) _stepW = Math.Max(_stepW, NumW + Measure(StripPrefix(label, _prefix)) + StepPad * 2);
                // A fan is measured from the middle of its box, so a wide one
                // hangs over the box's left edge.
                foreach (var label in _fanPitch.Keys)
                {
                    var col = _colOf[label];
                    var reach = 0;
                    foreach (var t in _outgoing[label].Where(_branchDx.ContainsKey)) reach = Math.Max(reach, -_branchDx[t] + BarHalf);
                    var over = reach - _stepW / 2;
                    if (over > 0) _fanLeft[col] = Math.Max(Get(_fanLeft, col), over);
                }
                // Side lanes and the inbound marker live in the gutter LEFT of a
                // column; the marker left of every lane.
                var sideCount = new Dictionary<int, int>();
                foreach (var t in _sides) sideCount[_colOf[t.Source]] = Get(sideCount, _colOf[t.Source]) + 1;
                var inboundW = Enumerable.Range(0, _chains.Count).ToDictionary(index => index, index => InboundW);
                foreach (var entry in _inboundOf)
                {
                    var col = _colOf[entry.Key];
                    inboundW[col] = Math.Max(inboundW[col], Measure(string.Join(", ", entry.Value)) + 10);
                }
                for (var index = 0; index < _chains.Count; index++) _gutter[index] = inboundW[index] + LaneW * Get(sideCount, index) + Get(_fanLeft, index);
                // A column is as wide as the longest receptivity drawn right of
                // its bars: per column, so one wide divergence does not push every
                // column apart.
                var guardRoom = Enumerable.Range(0, _chains.Count).ToDictionary(index => index, index => 0);
                foreach (var t in Drawn())
                {
                    var col = _colOf[t.Source];
                    int room;
                    if (_forkSet.Contains(t))
                    {
                        // Its bar stands on the target column's axis.
                        col = _colOf[t.Target];
                        room = BarHalf + GuardGap + Measure(ClipGuard(t.Guard));
                    }
                    else if (_branchDx.ContainsKey(t)) room = _branchDx[t] + _fanPitch[t.Source] - FanGap;
                    else
                    {
                        room = BarHalf + GuardGap + Measure(ClipGuard(t.Guard));
                        if (_jumpSet.Contains(t)) room = Math.Max(room, JumpW + 10 + Measure(Note(t)));
                    }
                    guardRoom[col] = Math.Max(guardRoom[col], room);
                }
                var x = LeftMargin;
                for (var index = 0; index < _chains.Count; index++)
                {
                    x += _gutter[index];
                    _colX[index] = x;
                    x += _stepW + guardRoom[index] + ColGap;
                }
            }

            // The priority block as a GRAFCET divergence: one stem out of the
            // "any" box onto a rail, every priority transition dropping off it
            // into its target's chip; drops into one target meet above one chip.
            void PriorityBlock()
            {
                if (_globals.Count == 0) return;
                var chipW = _globals.Aggregate(StepMinW, (w, t) => Math.Max(w, NumW + Measure(StripPrefix(t.Target, _prefix)) + StepPad * 2));
                var anyGuardRoom = _globals.Aggregate(0, (room, t) => Math.Max(room, BarHalf + GuardGap + Measure(ClipGuard(t.Guard))));
                var branchPitch = Math.Max(chipW, chipW / 2 + anyGuardRoom) + BranchGap;
                var groups = _globals.GroupBy(t => t.Target).Select(group => group.ToList()).ToList();
                var count = _globals.Count;
                var firstX = LeftMargin + InboundW + chipW / 2;
                var branchX = Enumerable.Range(0, count).Select(k => firstX + k * branchPitch).ToList();
                var anyY = TopMargin;
                var railY = anyY + StepH + AnyStem;
                var barY = railY + ForkDrop;
                // The convergence rail runs below the receptivities, not through them.
                var chipY = barY + BarUp + (groups.Any(group => group.Count > 1) ? MergeRail : 0);
                var mergeY = chipY - MergeRail;
                // Over the middle of the rail: a lone priority transition draws as one drop.
                var anyCx = (branchX[0] + branchX[count - 1]) / 2;
                _anyBox = new[] { anyCx - AnyW / 2, anyY, AnyW, StepH };
                var k = 0;
                foreach (var group in groups)
                {
                    var xs = branchX.GetRange(k, group.Count);
                    k += group.Count;
                    var cx = (xs[0] + xs[xs.Count - 1]) / 2;
                    var target = group[0].Target;
                    var chip = new Box { Number = _numberOf[target], Label = StripPrefix(target, _prefix), X = cx - chipW / 2, Y = chipY, W = chipW, H = StepH };
                    _chips.Add(chip);
                    for (var i = 0; i < group.Count; i++)
                    {
                        var x = xs[i];
                        var points = new List<int[]> { P(anyCx, anyY + StepH), P(anyCx, railY), P(x, railY) };
                        if (group.Count > 1) points.AddRange(new[] { P(x, mergeY), P(cx, mergeY), P(cx, chip.Y) });
                        else points.Add(P(x, chip.Y));
                        Add("global", group[i], points, x, barY, "h", new object[] { cx, chip.Y, "down" });
                    }
                }
                // Half a row: nothing is drawn between the chips and the first
                // step, and a full blank row reads as a missing link.
                _top = _chips.Max(chip => chip.Bottom) + RowGap / 2;
            }

            // The steps on the row grid; a row is as tall as its busiest step's
            // divergence needs.
            void BuildSteps()
            {
                var rowDemand = new Dictionary<int, int>();
                foreach (var label in _order) rowDemand[_rowOf[label]] = Math.Max(Get(rowDemand, _rowOf[label]), Get(_demand, label));
                var rowY = new Dictionary<int, int>();
                var y = _top;
                for (var r = 0; r <= _rowOf.Values.Max(); r++)
                {
                    rowY[r] = y;
                    y += StepH + Math.Max(RowGap, Get(rowDemand, r) + RowTail);
                }
                var priority = new HashSet<string>(_globals.Select(t => t.Target));
                foreach (var label in _order)
                {
                    var col = _colOf[label];
                    var step = new Box
                    {
                        Number = _numberOf[label], Label = StripPrefix(label, _prefix), FullLabel = label,
                        X = _colX[col], Y = rowY[_rowOf[label]], W = _stepW, H = StepH,
                        Initial = label == _order[0], Priority = priority.Contains(label), Col = col, Row = _rowOf[label],
                        Inbound = _inboundOf.TryGetValue(label, out var inbound) ? inbound : new List<int>(),
                        InboundX = _colX[col] - _gutter[col],
                    };
                    _steps.Add(step);
                    _stepOf[label] = step;
                }
            }

            // The page grown until it holds every drawn element.
            int[] Extent()
            {
                var width = LeftMargin + InboundW + _stepW + 60;
                var height = 0;
                if (_anyBox != null) { width = Math.Max(width, _anyBox[0] + _anyBox[2]); height = Math.Max(height, _anyBox[1] + _anyBox[3]); }
                foreach (var chip in _chips) { width = Math.Max(width, chip.Right); height = Math.Max(height, chip.Bottom); }
                foreach (var step in _steps) { width = Math.Max(width, step.Right + 20); height = Math.Max(height, step.Bottom); }
                foreach (var link in _links)
                {
                    foreach (var point in link.Points) { width = Math.Max(width, point[0] + 30); height = Math.Max(height, point[1]); }
                    width = Math.Max(width, link.GuardAt[0] + link.GuardW + 20);
                    height = Math.Max(height, link.GuardAt[1] + TextH);
                    if (link.NoteAt != null) { width = Math.Max(width, link.NoteAt[0] + link.NoteW + 20); height = Math.Max(height, link.NoteAt[1] + TextH); }
                }
                return new[] { width, height + BottomMargin };
            }
        }
    }
}
