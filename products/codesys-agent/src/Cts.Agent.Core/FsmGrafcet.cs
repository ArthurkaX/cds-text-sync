// GRAFCET-styled (IEC 60848) geometry of a machine FsmDetector found, the
// drawing the FSM window (FsmView) makes.
//
// Not a strict grafcet: steps are numbered boxes, the initial step is
// double-bordered, a transition is a bar across the link with its receptivity
// beside it, flow runs top to bottom. A CASE block is an arbitrary directed
// graph rather than a sequence, so it is cut into chains, one per column: the
// dominant path is the first column and each side sequence splits off into its
// own, starting at the row it branches from. A step with more than one way out
// is an OR divergence: one stem down to a single rail and one branch per
// transition, side by side in source order. Branches on one row that fall into
// the same step below are an OR convergence: they meet on a rail just above it.
// A forward skip within a column runs down a lane in the gutter to its left; a
// backward hop, and anything longer, is a connector - a hook naming its target
// - and the target records who arrives there. Transitions written outside the
// CASE hang under an "any" box above the steps, one chip per target.
using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    internal static partial class FsmGrafcet
    {
        const int StepH = 34, StepMinW = 170, StepPad = 18, NumW = 34;
        const int TopMargin = 24, BottomMargin = 28, LeftMargin = 24;
        const int BranchBarX = 26, BarHalf = 15, LaneW = 24, LaneClear = 24;
        const int GuardGap = 12, GuardChars = 40, TextH = 15, SelfW = 24, AnyW = 96, CharW = 7;
        //: Step bottom to the next step's top: a bar and two text lines.
        const int RowGap = 62;
        const int ColGap = 44;
        //: The bar sits this far above the step it leads into.
        const int BarUp = 30;
        //: A link drops this far before turning sideways.
        const int ForkDrop = 20;
        const int AnyStem = 22, BranchGap = 44;
        //: A longer backward hop becomes a connector, not a line.
        const int JumpMaxRows = 3;
        const int JumpH = 30, JumpGap = 10, JumpW = 22;
        //: The left gutter for the "N, M" marker on a connector's target.
        const int InboundW = 26;
        const int MergeRail = 20, RowTail = 28;
        //: A fork turns sideways this far below its bar, clear of the receptivity beside it.
        const int ForkTurn = 14;
        const int FanRail = 20, FanBar = 14, FanGap = 14;
        const string Always = "=1";

        sealed class Edge { internal int Index; internal string Source, Target, Guard; }
        sealed class Chain { internal readonly List<string> Labels = new List<string>(); internal int EntryRow; }
        sealed class Box
        {
            internal int Number, X, Y, W, H, Col, Row, InboundX;
            internal string Label, FullLabel;
            internal bool Initial, Priority;
            internal List<int> Inbound = new List<int>();
            internal int Right => X + W;
            internal int Bottom => Y + H;
            internal int Cx => X + W / 2;
            internal int Cy => Y + H / 2;
        }
        sealed class Link
        {
            internal string Kind, GuardText, NoteText = "";
            internal Edge Transition;
            internal List<int[]> Points;
            internal object[] Bar, Arrow;
            internal int[] GuardAt, NoteAt;
            internal int GuardW, NoteW;
        }

        // The geometry of one machine of FsmDetector.Machines, as the FSM
        // window reads it: width, height, prefix, dropped, columns, any_box,
        // steps, chips, links (transition_index into the machine's
        // transitions) and the metrics a drawing needs besides coordinates.
        internal static Dictionary<string, object> Layout(IDictionary<string, object> machine)
        {
            var labels = Rows(machine, "states").Select(state => (string)state["label"]).ToList();
            var edges = Rows(machine, "transitions").Select((row, i) => new Edge { Index = i, Source = row["source"] as string, Target = (string)row["target"], Guard = row["guard"] as string ?? "" }).ToList();
            return new Grafcet(labels, edges).Payload();
        }

        static IEnumerable<IDictionary<string, object>> Rows(IDictionary<string, object> machine, string key)
            => ((System.Collections.IEnumerable)machine[key]).Cast<IDictionary<string, object>>();

        static int Measure(string text) => (text ?? "").Length * CharW;

        // The dotted enum prefix every label shares, its dot included; "" unless
        // every label is dotted and they all share one.
        static string CommonPrefix(List<string> labels)
        {
            if (labels.Count == 0 || labels.Any(label => !label.Contains("."))) return "";
            var parts = labels.Select(label => label.Substring(0, label.LastIndexOf('.'))).Distinct().ToList();
            return parts.Count == 1 && parts[0].Length > 0 ? parts[0] + "." : "";
        }

        static string StripPrefix(string label, string prefix) => prefix.Length > 0 && label.StartsWith(prefix, StringComparison.Ordinal) ? label.Substring(prefix.Length) : label;

        // The receptivity as drawn beside a transition bar.
        static string ClipGuard(string guard)
        {
            var collapsed = StText.Squeezed(guard);
            if (collapsed.Length == 0) return Always;
            return collapsed.Length <= GuardChars ? collapsed : collapsed.Substring(0, GuardChars - 3) + "...";
        }

        // A state no other state enters is the initial step when it is the
        // only one; else the first CASE branch. A self transition says nothing
        // about entry order; one from outside the CASE does: a state entered
        // only by an `IF stop` is a reaction state, not the start.
        static string InitialLabel(List<string> labels, List<Edge> edges)
        {
            var incoming = labels.Distinct().ToDictionary(label => label, label => 0);
            foreach (var t in edges.Where(t => t.Source != t.Target && incoming.ContainsKey(t.Target))) incoming[t.Target]++;
            var roots = labels.Where(label => incoming[label] == 0).ToList();
            return roots.Count == 1 ? roots[0] : labels[0];
        }

        // The graph cut into vertical chains, one per column: walking the first
        // unvisited way out until it runs out gives one; whatever is left starts
        // the next, one row below where it splits off.
        static List<Chain> BuildChains(List<string> labels, List<Edge> edges)
        {
            var chains = new List<Chain>();
            if (labels.Count == 0) return chains;
            var known = new HashSet<string>(labels);
            var outgoing = new Dictionary<string, List<string>>();
            foreach (var t in edges)
            {
                if (t.Source == null || t.Source == t.Target || !known.Contains(t.Source) || !known.Contains(t.Target)) continue;
                if (!outgoing.TryGetValue(t.Source, out var targets)) outgoing[t.Source] = targets = new List<string>();
                if (!targets.Contains(t.Target)) targets.Add(t.Target);
            }
            List<string> Out(string label) => outgoing.TryGetValue(label, out var targets) ? targets : new List<string>();
            var visited = new HashSet<string>();
            var rowOf = new Dictionary<string, int>();
            var seeds = new List<Tuple<string, string>> { Tuple.Create(InitialLabel(labels, edges), (string)null) };
            var rest = new List<string>(labels);
            while (seeds.Count > 0 || rest.Count > 0)
            {
                if (seeds.Count == 0)
                {
                    // Nothing walked reaches it (often the steps a priority
                    // transition enters): it starts its own chain at row 0 and is
                    // walked like the first.
                    seeds.Add(Tuple.Create(rest[0], (string)null));
                    rest.RemoveAt(0);
                    continue;
                }
                var seed = seeds[0];
                seeds.RemoveAt(0);
                if (visited.Contains(seed.Item1)) continue;
                var chain = new Chain { EntryRow = seed.Item2 == null ? 0 : rowOf[seed.Item2] + 1 };
                var row = chain.EntryRow;
                for (var current = seed.Item1; current != null && !visited.Contains(current);)
                {
                    visited.Add(current);
                    rowOf[current] = row++;
                    chain.Labels.Add(current);
                    current = Out(current).FirstOrDefault(target => !visited.Contains(target));
                }
                chains.Add(chain);
                foreach (var source in chain.Labels)
                    foreach (var target in Out(source).Where(target => !visited.Contains(target)))
                        seeds.Add(Tuple.Create(target, source));
            }
            return chains;
        }

        // Greedy interval colouring of (y, y) spans in either order: a lane
        // index per span, the lowest free lane first, so the topmost link hugs
        // the steps.
        static int[] AssignLanes(List<Tuple<int, int>> spans)
        {
            var normal = spans.Select(span => Tuple.Create(Math.Min(span.Item1, span.Item2), Math.Max(span.Item1, span.Item2))).ToList();
            var laneEnd = new List<int>();
            var result = new int[normal.Count];
            foreach (var i in Enumerable.Range(0, normal.Count).OrderBy(i => normal[i].Item1).ThenBy(i => normal[i].Item2))
            {
                var lane = laneEnd.FindIndex(end => end + 8 < normal[i].Item1);
                if (lane < 0) { lane = laneEnd.Count; laneEnd.Add(0); }
                result[i] = lane;
                laneEnd[lane] = normal[i].Item2;
            }
            return result;
        }

        static int[] P(int x, int y) => new[] { x, y };

        // One machine's layout, worked out stage by stage: each fills in what
        // the next reads.
        sealed partial class Grafcet
        {
            readonly List<string> _labels;
            readonly List<Edge> _edges;
            List<Chain> _chains;
            List<string> _order;
            string _prefix = "";
            readonly Dictionary<string, int> _numberOf = new Dictionary<string, int>();
            readonly Dictionary<string, int> _colOf = new Dictionary<string, int>();
            readonly Dictionary<string, int> _rowOf = new Dictionary<string, int>();
            readonly List<Edge> _globals = new List<Edge>(), _selfs = new List<Edge>(), _graph = new List<Edge>();
            int _dropped;
            List<Edge> _chainLinks = new List<Edge>(), _forks = new List<Edge>(), _sides = new List<Edge>(), _jumps = new List<Edge>(), _merges = new List<Edge>();
            HashSet<Edge> _axis, _forkSet, _jumpSet;
            readonly Dictionary<string, List<Edge>> _outgoing = new Dictionary<string, List<Edge>>();
            readonly Dictionary<Edge, int> _branchDx = new Dictionary<Edge, int>();
            readonly HashSet<Edge> _fanTrunk = new HashSet<Edge>();
            readonly Dictionary<string, int> _fanPitch = new Dictionary<string, int>();
            readonly Dictionary<string, int> _demand = new Dictionary<string, int>();
            readonly Dictionary<string, List<int>> _inboundOf = new Dictionary<string, List<int>>();
            int _stepW = StepMinW;
            readonly Dictionary<int, int> _fanLeft = new Dictionary<int, int>(), _gutter = new Dictionary<int, int>(), _colX = new Dictionary<int, int>();
            readonly List<Link> _links = new List<Link>();
            readonly List<Box> _chips = new List<Box>();
            int[] _anyBox;
            int _top = TopMargin;
            readonly List<Box> _steps = new List<Box>();
            readonly Dictionary<string, Box> _stepOf = new Dictionary<string, Box>();

            internal Grafcet(List<string> labels, List<Edge> edges) { _labels = labels; _edges = edges; }

            internal Dictionary<string, object> Payload()
            {
                _chains = BuildChains(_labels, _edges);
                if (_chains.Count == 0) return Result(LeftMargin * 2, TopMargin + BottomMargin, 1);
                Prepare();
                Partition();
                Classify();
                Convergence();
                Divergence();
                Inbound();
                MeasureColumns();
                PriorityBlock();
                BuildSteps();
                ChainLinks();
                ForkLinks();
                SelfLinks();
                SideLinks();
                JumpLinks();
                MergeLinks();
                var extent = Extent();
                return Result(extent[0], extent[1], _chains.Count);
            }

            void Prepare()
            {
                _order = _chains.SelectMany(chain => chain.Labels).ToList();
                _prefix = CommonPrefix(_order);
                for (var i = 0; i < _order.Count; i++) _numberOf[_order[i]] = i + 1;
                for (var index = 0; index < _chains.Count; index++)
                    for (var offset = 0; offset < _chains[index].Labels.Count; offset++)
                    {
                        _colOf[_chains[index].Labels[offset]] = index;
                        _rowOf[_chains[index].Labels[offset]] = _chains[index].EntryRow + offset;
                    }
            }

            bool Known(string label) => label != null && _colOf.ContainsKey(label);

            // A transition from outside the CASE into a known state is a
            // priority one, a state into itself a self link, a state-to-state
            // edge part of the graph; anything else is dropped.
            void Partition()
            {
                foreach (var t in _edges)
                {
                    if (t.Source == null && Known(t.Target)) _globals.Add(t);
                    else if (t.Source == t.Target && Known(t.Source)) _selfs.Add(t);
                    else if (Known(t.Source) && Known(t.Target)) _graph.Add(t);
                    else _dropped++;
                }
            }

            void Classify()
            {
                var claimed = new HashSet<Tuple<int, int>>();
                foreach (var t in _graph)
                {
                    int sCol = _colOf[t.Source], tCol = _colOf[t.Target], sRow = _rowOf[t.Source], tRow = _rowOf[t.Target];
                    if (sCol == tCol && tRow == sRow + 1 && claimed.Add(Tuple.Create(sCol, sRow))) _chainLinks.Add(t);
                    else if (sCol != tCol && tRow == sRow + 1 && t.Target == _chains[tCol].Labels[0]) _forks.Add(t);
                    // Forward only: going back is a named hand-off like any
                    // other distant target, a connector.
                    else if (sCol == tCol && sRow < tRow && tRow <= sRow + JumpMaxRows) _sides.Add(t);
                    else _jumps.Add(t);
                }
            }

            // Branches standing side by side on one row that all fall into the
            // step below them: an OR convergence, every branch with its own
            // receptivity, meeting on one rail. They stand side by side when they
            // leave different columns or are branches of one step's divergence.
            void Convergence()
            {
                var byTarget = new Dictionary<string, List<Edge>>();
                foreach (var t in _graph)
                {
                    if (!byTarget.TryGetValue(t.Target, out var group)) byTarget[t.Target] = group = new List<Edge>();
                    group.Add(t);
                }
                foreach (var target in byTarget.Keys.OrderBy(key => key, StringComparer.Ordinal))
                {
                    var group = byTarget[target];
                    if (group.Count < 2) continue;
                    var rows = group.Select(t => _rowOf[t.Source]).Distinct().ToList();
                    if (rows.Count != 1) continue;
                    if (group.Select(t => _colOf[t.Source]).Distinct().Count() != group.Count && group.Select(t => t.Source).Distinct().Count() != 1) continue;
                    if (_rowOf[target] != rows[0] + 1) continue;
                    _merges.AddRange(group);
                }
                if (_merges.Count == 0) return;
                var merged = new HashSet<Edge>(_merges);
                _chainLinks = _chainLinks.Where(t => !merged.Contains(t)).ToList();
                _forks = _forks.Where(t => !merged.Contains(t)).ToList();
                _sides = _sides.Where(t => !merged.Contains(t)).ToList();
                _jumps = _jumps.Where(t => !merged.Contains(t)).ToList();
                _merges = _merges.OrderBy(t => _colOf[t.Source]).ToList();
            }

            IEnumerable<Edge> Drawn() => _chainLinks.Concat(_forks).Concat(_sides).Concat(_jumps).Concat(_merges);

            string Note(Edge t) => _numberOf[t.Target] + "  " + StripPrefix(t.Target, _prefix);

            // A step with more than one way out fans its transitions out
            // sideways in source order, so they read as the IF/ELSIF list they
            // came from rather than as transitions in series.
            void Divergence()
            {
                _jumpSet = new HashSet<Edge>(_jumps);
                // A branch that carries its column on: same column, one row down.
                _axis = new HashSet<Edge>(_chainLinks.Concat(_sides).Concat(_jumps).Concat(_merges)
                    .Where(t => _colOf[t.Source] == _colOf[t.Target] && _rowOf[t.Target] == _rowOf[t.Source] + 1));
                _forkSet = new HashSet<Edge>(_forks);
                foreach (var t in Drawn())
                {
                    if (!_outgoing.TryGetValue(t.Source, out var group)) _outgoing[t.Source] = group = new List<Edge>();
                    group.Add(t);
                }
                foreach (var label in _outgoing.Keys.ToList())
                {
                    var group = _outgoing[label] = _outgoing[label].OrderBy(t => t.Index).ToList();
                    if (group.Count < 2) continue;
                    // A fork's x is its target column's axis: the rail already
                    // reaches it, so it needs no slot.
                    var slotted = group.Where(t => !_forkSet.Contains(t)).ToList();
                    if (slotted.Count > 0)
                    {
                        // Every receptivity stands right of its own bar, so the
                        // branches stand as far apart as the widest reaches.
                        var pitch = 0;
                        foreach (var t in slotted)
                        {
                            pitch = Math.Max(pitch, BarHalf + GuardGap + Measure(ClipGuard(t.Guard)));
                            if (_jumpSet.Contains(t)) pitch = Math.Max(pitch, JumpW + 10 + Measure(Note(t)));
                        }
                        pitch += FanGap;
                        // The branch that carries the column on stays on its axis
                        // and the rest spread around it; without one the fan is centred.
                        var axisIndex = slotted.FindIndex(t => _axis.Contains(t));
                        var anchor = axisIndex >= 0 ? axisIndex : (slotted.Count - 1) / 2.0;
                        for (var index = 0; index < slotted.Count; index++)
                            _branchDx[slotted[index]] = (int)Math.Round((index - anchor) * pitch, MidpointRounding.ToEven);
                        _fanPitch[label] = pitch;
                    }
                    // A fan of nothing but connectors would leave its rail
                    // hanging under the step: the first of them draws the trunk.
                    if (group.All(t => _jumpSet.Contains(t))) _fanTrunk.Add(group[0]);
                    var need = FanRail + FanBar + TextH / 2 + 6;
                    foreach (var t in group)
                        need = Math.Max(need, _jumpSet.Contains(t) ? FanRail + FanBar + JumpGap + JumpH : FanRail + FanBar + ForkTurn);
                    _demand[label] = need;
                }
            }

            // Only a connector leaves nothing pointing at its target, so only its
            // target is marked with who arrives; the gutter must fit the marker.
            void Inbound()
            {
                foreach (var t in _jumps)
                {
                    if (!_inboundOf.TryGetValue(t.Target, out var sources)) _inboundOf[t.Target] = sources = new List<int>();
                    if (!sources.Contains(_numberOf[t.Source])) sources.Add(_numberOf[t.Source]);
                }
                foreach (var sources in _inboundOf.Values) sources.Sort();
            }

            Dictionary<string, object> Result(int width, int height, int columns)
            {
                return new Dictionary<string, object>
                {
                    ["width"] = width, ["height"] = height, ["prefix"] = _prefix, ["dropped"] = _dropped, ["columns"] = columns,
                    ["any_box"] = _anyBox?.Cast<object>().ToList(),
                    ["steps"] = _steps.Select(step => (object)new Dictionary<string, object>
                    {
                        ["number"] = step.Number, ["label"] = step.Label, ["full_label"] = step.FullLabel,
                        ["x"] = step.X, ["y"] = step.Y, ["w"] = step.W, ["h"] = step.H,
                        ["initial"] = step.Initial, ["priority"] = step.Priority, ["col"] = step.Col, ["row"] = step.Row,
                        ["inbound"] = step.Inbound.Cast<object>().ToList(), ["inbound_x"] = step.InboundX,
                    }).ToList(),
                    ["chips"] = _chips.Select(chip => (object)new Dictionary<string, object>
                    {
                        ["number"] = chip.Number, ["label"] = chip.Label, ["x"] = chip.X, ["y"] = chip.Y, ["w"] = chip.W, ["h"] = chip.H,
                    }).ToList(),
                    ["links"] = _links.Select(link => (object)new Dictionary<string, object>
                    {
                        ["kind"] = link.Kind, ["transition_index"] = link.Transition.Index,
                        ["points"] = link.Points.Select(point => (object)point.Cast<object>().ToList()).ToList(),
                        ["bar"] = link.Bar.ToList(), ["guard_text"] = link.GuardText, ["guard_at"] = link.GuardAt.Cast<object>().ToList(), ["guard_w"] = link.GuardW,
                        ["arrow"] = link.Arrow?.ToList(), ["note_text"] = link.NoteText, ["note_at"] = link.NoteAt?.Cast<object>().ToList(), ["note_w"] = link.NoteW,
                    }).ToList(),
                    ["metrics"] = new Dictionary<string, object> { ["num_w"] = NumW, ["text_h"] = TextH, ["bar_half"] = BarHalf },
                };
            }

            static int Get<TKey>(Dictionary<TKey, int> map, TKey key) => map.TryGetValue(key, out var value) ? value : 0;
        }
    }
}
