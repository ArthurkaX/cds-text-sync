using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    internal static partial class FsmGrafcet
    {
        // The links between the boxes: chains, forks, self links, side lanes, connectors and convergences.
        sealed partial class Grafcet
        {
            // A branch of a divergence: its stem, rail and drop to the branch's x.
            List<int[]> Fan(Box source, int x) => new List<int[]> { P(source.Cx, source.Bottom), P(source.Cx, source.Bottom + FanRail), P(x, source.Bottom + FanRail) };

            void ChainLinks()
            {
                foreach (var t in _chainLinks)
                {
                    Box source = _stepOf[t.Source], target = _stepOf[t.Target];
                    if (!_branchDx.ContainsKey(t))
                        // The only way out: the bar just above the step it leads into.
                        Add("chain", t, new List<int[]> { P(source.Cx, source.Bottom), P(source.Cx, target.Y) }, source.Cx, target.Y - BarUp, "h", null);
                    else
                    {
                        var x = source.Cx + _branchDx[t];
                        var points = Fan(source, x);
                        points.Add(P(x, target.Y));
                        Add("chain", t, points, x, source.Bottom + FanRail + FanBar, "h", null);
                    }
                }
            }

            // A branch landing in another column runs along the rail to the
            // target's axis and drops straight in.
            void ForkLinks()
            {
                foreach (var t in _forks)
                {
                    Box source = _stepOf[t.Source], target = _stepOf[t.Target];
                    var points = Fan(source, target.Cx);
                    points.Add(P(target.Cx, target.Y));
                    Add("fork", t, points, target.Cx, source.Bottom + FanRail + FanBar, "h", null);
                }
            }

            void SelfLinks()
            {
                foreach (var t in _selfs)
                {
                    var step = _stepOf[t.Source];
                    int cy = step.Cy, x0 = step.Right, x1 = x0 + SelfW;
                    var link = Add("self", t, new List<int[]> { P(x0, cy - 9), P(x1, cy - 9), P(x1, cy + 9), P(x0, cy + 9) }, x0 + SelfW / 2, cy - 9, "v", new object[] { x0, cy + 9, "left" });
                    link.GuardAt = P(x1 + GuardGap, cy - TextH / 2);
                }
            }

            // A forward skip runs down a lane in the gutter left of its column.
            void SideLinks()
            {
                for (var col = 0; col < _chains.Count; col++)
                {
                    var colSides = _sides.Where(t => _colOf[t.Source] == col).ToList();
                    if (colSides.Count == 0) continue;
                    var made = new List<Tuple<Link, Box, Box, int, int>>();
                    foreach (var t in colSides)
                    {
                        Box source = _stepOf[t.Source], target = _stepOf[t.Target];
                        Link link;
                        int exitY;
                        if (_branchDx.ContainsKey(t))
                        {
                            var x = source.Cx + _branchDx[t];
                            var barY = source.Bottom + FanRail + FanBar;
                            exitY = barY + ForkTurn;
                            var head = Fan(source, x);
                            head.Add(P(x, exitY));
                            link = Add("side", t, head, x, barY, "h", null);
                        }
                        else
                        {
                            exitY = source.Bottom + ForkDrop;
                            link = Add("side", t, new List<int[]> { P(source.Cx, source.Bottom), P(source.Cx, exitY) }, source.Cx - BranchBarX, exitY, "v", null);
                            // Beside the stem, not off the far side of the box.
                            link.GuardAt = P(source.Cx + GuardGap, exitY - TextH / 2);
                        }
                        made.Add(Tuple.Create(link, source, target, exitY, target.Cy));
                    }
                    var lanes = AssignLanes(made.Select(item => Tuple.Create(item.Item4, item.Item5)).ToList());
                    for (var i = 0; i < made.Count; i++)
                    {
                        var (link, source, target, exitY, entryY) = made[i];
                        var laneX = _colX[source.Col] - LaneClear - Get(_fanLeft, source.Col) - lanes[i] * LaneW;
                        link.Points.AddRange(new[] { P(laneX, exitY), P(laneX, entryY), P(target.X, entryY) });
                        link.Arrow = new object[] { target.X, entryY, "right" };
                    }
                }
            }

            // A connector: down out of the step, right, back up into an
            // arrowhead with the target named below its tip - the same hook
            // whether the target is above or below, a named hand-off.
            void JumpLinks()
            {
                foreach (var t in _jumps)
                {
                    Box source = _stepOf[t.Source], target = _stepOf[t.Target];
                    int x, barY;
                    List<int[]> head;
                    if (_branchDx.ContainsKey(t))
                    {
                        var railY = source.Bottom + FanRail;
                        x = source.Cx + _branchDx[t];
                        barY = railY + FanBar;
                        // From the rail: the trunk belongs to every branch and
                        // would take the connector's colour.
                        head = _fanTrunk.Contains(t) ? Fan(source, x) : new List<int[]> { P(source.Cx, railY), P(x, railY) };
                    }
                    else
                    {
                        x = source.Cx;
                        barY = source.Bottom + ForkDrop;
                        head = new List<int[]> { P(x, source.Bottom) };
                    }
                    int tipY = barY + JumpGap, footY = tipY + JumpH, hookX = x + JumpW;
                    head.AddRange(new[] { P(x, footY), P(hookX, footY), P(hookX, tipY) });
                    var link = Add("jump", t, head, x, barY, "h", new object[] { hookX, tipY, "up" });
                    link.NoteText = target.Number + "  " + target.Label;
                    link.NoteAt = P(hookX + 10, tipY + 2);
                    link.NoteW = Measure(link.NoteText);
                }
            }

            // The OR convergence: each branch through its own bar onto one rail
            // just above the target, one stem into it.
            void MergeLinks()
            {
                foreach (var t in _merges)
                {
                    Box source = _stepOf[t.Source], target = _stepOf[t.Target];
                    var railY = target.Y - MergeRail;
                    int x, barY;
                    List<int[]> points;
                    if (_branchDx.ContainsKey(t))
                    {
                        x = source.Cx + _branchDx[t];
                        barY = source.Bottom + FanRail + FanBar;
                        points = Fan(source, x);
                        points.Add(P(x, railY));
                    }
                    else
                    {
                        x = source.Cx;
                        barY = source.Bottom + ForkDrop;
                        points = new List<int[]> { P(x, source.Bottom), P(x, railY) };
                    }
                    points.AddRange(new[] { P(target.Cx, railY), P(target.Cx, target.Y) });
                    Add("merge", t, points, x, barY, "h", null);
                }
            }

            // A link with its bar at (x, barY) and the receptivity right of it.
            Link Add(string kind, Edge t, List<int[]> points, int x, int barY, string way, object[] arrow)
            {
                var text = ClipGuard(t.Guard);
                var link = new Link { Kind = kind, Transition = t, Points = points, Bar = new object[] { x, barY, way }, GuardText = text, GuardAt = P(x + BarHalf + GuardGap, barY - TextH / 2), GuardW = Measure(text), Arrow = arrow };
                _links.Add(link);
                return link;
            }
        }
    }
}
