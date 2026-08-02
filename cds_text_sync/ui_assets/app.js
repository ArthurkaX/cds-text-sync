/* Shared, dependency-free UI helpers for the static analyzer webview. */
(function (global) {
  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[ch];
    });
  }

  function locationText(location) {
    location = location || {};
    return (location.path || "Project") +
      (location.line ? ":" + location.line + (location.column ? ":" + location.column : "") : "");
  }

  global.CTSUi = { escapeHtml: escapeHtml, locationText: locationText };
})(window);
