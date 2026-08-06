/* Shared, dependency-free UI helpers for the static analyzer webview. */
(function (global) {
  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[ch];
    });
  }

  function locationText(location) {
    location = location || {};
    var span = "";
    if (location.line) {
      span = ":" + location.line;
      if (location.end_line && location.end_line > location.line) span += "-" + location.end_line;
      if (location.column) span += ":" + location.column;
    }
    return (location.path || "Project") + span;
  }

  /* Lines a finding actually occupies. A merged finding carries every one of
     them; an unmerged one is its single line. */
  function occurrenceLines(finding) {
    finding = finding || {};
    if (Array.isArray(finding.member_lines) && finding.member_lines.length) {
      return finding.member_lines.slice();
    }
    var line = finding.location && finding.location.line;
    return line ? [line] : [];
  }

  /* Short label for where a finding sits: a range when its members are a
     contiguous block, a list when they are scattered. */
  function findingRange(finding, maxListed) {
    finding = finding || {};
    var location = finding.location || {}, line = location.line;
    if (!line) return "—";
    if (location.end_line && location.end_line > line) return "L" + line + "–" + location.end_line;
    var lines = occurrenceLines(finding);
    if (lines.length < 2) return "L" + line;
    var limit = maxListed || 3;
    var shown = lines.slice(0, limit).map(function (n) { return "L" + n; }).join(", ");
    return lines.length > limit ? shown + ", +" + (lines.length - limit) : shown;
  }

  /* ---- Progress reporting -------------------------------------------------
     The bridge reports (phase, done, total, detail) while a run is in flight.
     Each phase counts something different - files, then rules - so the bar
     gives every phase a slice of its own and moves forward within it. The
     slice widths are a guess at the usual shape of a run; the label is what
     carries the exact numbers, so an unusual project makes the bar uneven,
     never wrong. */
  var PROGRESS_SLICES = {
    start: [0, 0.02],
    parse: [0.02, 0.55],
    prepare: [0.55, 0.62],
    rules: [0.62, 0.97],
    finalize: [0.97, 1],
  };

  var PROGRESS_LABEL = {
    start: "Starting analysis",
    parse: "Reading sources",
    prepare: "Preparing rules",
    rules: "Running rules",
    finalize: "Collecting findings",
  };

  /* Fraction of the whole run, or null when the phase says nothing useful -
     the caller then shows an indeterminate bar rather than a made-up number. */
  function progressFraction(report) {
    report = report || {};
    var slice = PROGRESS_SLICES[report.phase];
    if (!slice) return null;
    var total = Number(report.total) || 0;
    var done = Number(report.done) || 0;
    var within = total > 0 ? Math.min(done, total) / total : 0;
    return slice[0] + (slice[1] - slice[0]) * within;
  }

  function progressLabel(report) {
    report = report || {};
    var label = PROGRESS_LABEL[report.phase];
    if (!label) return "Running analysis…";
    var total = Number(report.total) || 0;
    var done = Math.min(Number(report.done) || 0, total);
    /* A one-step phase has nothing to count: "Collecting findings · 1/1"
       says less than the phase name on its own. */
    if (total < 2) return label + "…";
    /* Naming the rule in flight is more use than the count alone: a run that
       looks stuck is usually stuck in one identifiable rule. */
    if (report.phase === "rules" && report.detail) {
      return report.detail + " · " + done + "/" + total + " rules";
    }
    return label + " · " + done + "/" + total;
  }

  global.CTSUi = {
    escapeHtml: escapeHtml,
    locationText: locationText,
    occurrenceLines: occurrenceLines,
    findingRange: findingRange,
    progressFraction: progressFraction,
    progressLabel: progressLabel,
  };
})(window);
