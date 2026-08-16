/* CTS FSM map - window logic.

   Everything the backend returns is derived from user ST source, so it is
   built into the DOM with textContent, never with innerHTML. The single
   exception is the `svg` field, which cds_text_sync.fsm.render already
   XML-escaped; it is inserted in exactly one place, drawDiagram().
*/
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  var POLL_MS = 180;
  var TERMINAL = { completed: true, cancelled: true, failed: true };

  var state = {
    workspace: "",
    files: [],           // backend order; never re-sorted
    rows: {},            // path -> {state, count, error}
    jobId: null,
    cursor: 0,
    jobState: "",
    counts: { total: 0, completed: 0, hits: 0, errors: 0 },
    timer: null,
    filterText: "",
    filterState: "all",
    selected: "",
    machine: 0,
    render: null,
    transition: null,
    stateLabel: null,
    zoom: 1,
    panX: 0,
    panY: 0,
  };

  /* ---- notices --------------------------------------------------------- */

  function notify(message, kind) {
    var box = $("notice");
    box.textContent = message || "";
    box.className = "banner " + (kind || "");
    box.classList.toggle("hidden", !message);
  }

  /* A bridge call that comes back with ok:false is a real failure the user
     has to see; swallowing it would leave the window looking merely idle. */
  function failed(response, fallback) {
    if (!response) {
      notify(fallback, "error");
      return true;
    }
    if (response.ok === false) {
      notify(response.error || fallback, "error");
      return true;
    }
    return false;
  }

  function call(name) {
    var args = Array.prototype.slice.call(arguments, 1);
    return window.pywebview.api[name].apply(window.pywebview.api, args)
      .catch(function (error) {
        return { ok: false, error: String((error && error.message) || error) };
      });
  }

  /* ---- workspace ------------------------------------------------------- */

  function applyBootstrap(payload) {
    if (failed(payload, "Could not open the workspace.")) {
      state.files = [];
      state.rows = {};
      renderFiles();
      renderProgress();
      return false;
    }
    notify("");
    state.workspace = payload.workspace || "";
    state.files = payload.files || [];
    state.rows = {};
    state.selected = "";
    state.render = null;
    $("workspace-path").textContent = state.workspace || "No workspace";
    showSnapshot(payload.snapshot);
    renderFiles();
    renderDiagram();
    renderProgress();
    return true;
  }

  function showSnapshot(snapshot) {
    var box = $("snapshot");
    if (!snapshot || !snapshot.message) {
      box.classList.add("hidden");
      return;
    }
    box.textContent = snapshot.message;
    box.className = "banner " + (snapshot.state || "");
    box.classList.remove("hidden");
  }

  /* ---- scanning -------------------------------------------------------- */

  function startScan() {
    stopPolling();
    return call("start_scan", null).then(function (started) {
      if (failed(started, "Could not start the scan.")) return;
      state.jobId = started.job_id;
      state.cursor = 0;
      state.jobState = "queued";
      state.counts = {
        total: started.total || 0, completed: 0, hits: 0, errors: 0,
      };
      $("stop").disabled = false;
      renderProgress();
      poll();
    });
  }

  function stopPolling() {
    if (state.timer) {
      window.clearTimeout(state.timer);
      state.timer = null;
    }
  }

  function poll() {
    var jobId = state.jobId;
    call("poll_scan", jobId, state.cursor).then(function (payload) {
      /* A poll that lands after the job was superseded must not move the
         cursor of the job that replaced it. */
      if (jobId !== state.jobId) return;
      if (failed(payload, "The scan could not be polled.")) {
        $("stop").disabled = true;
        return;
      }
      state.cursor = payload.cursor;
      state.jobState = payload.state;
      state.counts = {
        total: payload.total || 0,
        completed: payload.completed || 0,
        hits: payload.hits || 0,
        errors: payload.errors || 0,
      };
      (payload.events || []).forEach(recordEvent);
      renderFiles();
      renderProgress();
      if (TERMINAL[payload.state]) {
        $("stop").disabled = true;
        if (payload.state === "failed") {
          notify("The scan failed: " + (payload.error || "unknown error"), "error");
        }
        return;
      }
      state.timer = window.setTimeout(poll, POLL_MS);
    });
  }

  function recordEvent(event) {
    state.rows[event.path] = {
      state: event.state,
      count: (event.machines || []).length,
      error: event.error || "",
    };
  }

  /* ---- file list ------------------------------------------------------- */

  function rowState(path) {
    var row = state.rows[path];
    return row ? row.state : "pending";
  }

  function visible(path) {
    if (state.filterText &&
        path.toLowerCase().indexOf(state.filterText) === -1) return false;
    if (state.filterState === "all") return true;
    return rowState(path) === state.filterState;
  }

  function badgeText(path) {
    var row = state.rows[path];
    if (!row) return "…";
    if (row.state === "error") return "error";
    if (row.state === "fsm") return row.count === 1 ? "1 FSM" : row.count + " FSM";
    return "no FSM";
  }

  function renderFiles() {
    var list = $("file-list");
    list.textContent = "";
    var shown = 0;
    state.files.forEach(function (entry) {
      var path = entry.path;
      if (!visible(path)) return;
      shown += 1;
      var item = document.createElement("li");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "file-row" + (path === state.selected ? " selected" : "");
      var name = document.createElement("span");
      name.className = "name";
      name.textContent = path;
      name.title = path;
      var badge = document.createElement("span");
      badge.className = "badge " + rowState(path);
      badge.textContent = badgeText(path);
      button.appendChild(name);
      button.appendChild(badge);
      button.addEventListener("click", function () { select(path); });
      item.appendChild(button);
      list.appendChild(item);
    });
    if (!shown) {
      var empty = document.createElement("li");
      empty.className = "empty-note";
      empty.textContent = state.files.length
        ? "No file matches this filter."
        : "No .st files in this workspace.";
      list.appendChild(empty);
    }
  }

  function renderProgress() {
    var counts = state.counts;
    var parts = [counts.completed + " / " + counts.total + " scanned"];
    parts.push(counts.hits + " with FSM");
    parts.push(counts.errors + " error" + (counts.errors === 1 ? "" : "s"));
    if (state.jobState && !TERMINAL[state.jobState]) parts.push("scanning…");
    $("progress").textContent = parts.join(" · ");
  }

  /* ---- selection ------------------------------------------------------- */

  function select(path) {
    state.selected = path;
    state.machine = 0;
    renderFiles();
    /* A file the scan has not reached yet is analysed on demand so the click
       does not wait behind the rest of the queue. */
    if (!state.rows[path]) {
      $("summary").textContent = "Analysing " + path + "…";
      call("analyze_file", path).then(function (row) {
        if (state.selected !== path) return;
        if (failed(row, "Could not analyse " + path)) return;
        recordEvent(row);
        renderFiles();
        loadRender();
      });
      return;
    }
    loadRender();
  }

  function loadRender() {
    var path = state.selected;
    var machine = state.machine;
    /* Whatever the popup was showing belongs to the previous drawing. */
    closePopup();
    call("render", path, machine).then(function (payload) {
      if (state.selected !== path || state.machine !== machine) return;
      if (failed(payload, "Could not render " + path)) {
        state.render = null;
        renderDiagram();
        return;
      }
      state.render = payload;
      state.transition = null;
      state.stateLabel = null;
      renderDiagram();
      zoomToFit();
    });
  }

  /* ---- diagram --------------------------------------------------------- */

  function renderDiagram() {
    var payload = state.render;
    var host = $("svg-host");
    var picker = $("machine-select");
    var empty = $("empty-state");

    if (!payload || !payload.count) {
      host.textContent = "";
      picker.classList.add("hidden");
      $("summary").textContent = "";
      empty.textContent = !state.selected
        ? "Select a file on the left to draw its state machine."
        : "This file has no state machine. A CASE over a state variable whose "
          + "branches assign to that same variable is what makes one.";
      empty.classList.remove("hidden");
      renderTransitions();
      renderWarnings();
      return;
    }

    empty.classList.add("hidden");
    drawDiagram(payload.svg);
    /* drawDiagram replaces the SVG wholesale, so any highlight classes on it
       are gone; repaint them from state. */
    applyHighlight();
    renderMachinePicker(payload.count);
    renderSummary(payload.summary);
    renderTransitions();
    renderWarnings();
  }

  function drawDiagram(svg) {
    /* to_svg emits a standalone document, so it starts with an XML
       declaration the HTML parser has no use for; drop it and keep the
       <svg> root. */
    var markup = String(svg).replace(/^\s*<\?xml[^>]*\?>\s*/, "");
    /* The ONLY innerHTML in this file. `markup` is what the Python renderer
       built and escaped; every other backend value goes through textContent. */
    $("svg-host").innerHTML = markup;
  }

  function renderMachinePicker(count) {
    var picker = $("machine-select");
    picker.textContent = "";
    picker.classList.toggle("hidden", count < 2);
    if (count < 2) return;
    for (var index = 0; index < count; index += 1) {
      var option = document.createElement("option");
      option.value = String(index);
      option.textContent = "Machine " + (index + 1) + " of " + count;
      picker.appendChild(option);
    }
    picker.value = String(state.machine);
  }

  function renderSummary(summary) {
    if (!summary) {
      $("summary").textContent = "";
      return;
    }
    var parts = [
      "selector " + summary.selector,
      summary.state_count + " states",
      summary.transition_count + " transitions",
    ];
    if (summary.deferred) parts.push("deferred writes");
    if (summary.numeric) parts.push("numeric labels");
    var warnings = (state.render && state.render.warnings) || [];
    if (warnings.length) {
      parts.push(warnings.length + " warning" + (warnings.length === 1 ? "" : "s"));
    }
    $("summary").textContent = parts.join(" · ");
  }

  function renderTransitions() {
    var list = $("transition-list");
    list.textContent = "";
    var rows = (state.render && state.render.transitions) || [];
    if (!rows.length) {
      var empty = document.createElement("li");
      empty.className = "empty-note";
      empty.textContent = "No transitions.";
      list.appendChild(empty);
      return;
    }
    rows.forEach(function (row) {
      var related = state.stateLabel !== null
        && (row.source === state.stateLabel || row.target === state.stateLabel);
      var item = document.createElement("li");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "transition-row"
        + (row.index === state.transition ? " selected" : "")
        + (related ? " related" : "");

      var edge = document.createElement("span");
      edge.className = "edge";
      edge.textContent = (row.source || "(any)") + " → " + row.target;
      button.appendChild(edge);

      if (row.deferred) {
        var deferred = document.createElement("span");
        deferred.className = "deferred";
        deferred.textContent = " (deferred via " + row.lhs + ")";
        button.appendChild(deferred);
      }

      var guard = document.createElement("span");
      guard.className = "guard";
      /* The complete guard text, never abbreviated: CSS wraps it instead. */
      guard.textContent = row.guard ? row.guard : "unconditional";
      button.appendChild(guard);

      button.addEventListener("click", function () {
        selectTransition(row.index);
      });
      item.appendChild(button);
      list.appendChild(item);
    });
  }

  function renderWarnings() {
    var list = $("warning-list");
    list.textContent = "";
    var warnings = (state.render && state.render.warnings) || [];
    if (!warnings.length) {
      var empty = document.createElement("li");
      empty.className = "empty-note";
      empty.textContent = "No warnings.";
      list.appendChild(empty);
      return;
    }
    warnings.forEach(function (warning) {
      var item = document.createElement("li");
      var offset = document.createElement("span");
      offset.className = "offset";
      offset.textContent = "@" + warning[0] + " ";
      item.appendChild(offset);
      item.appendChild(document.createTextNode(String(warning[1])));
      list.appendChild(item);
    });
  }

  function selectTransition(index) {
    var same = state.transition === index;
    state.transition = same ? null : index;
    state.stateLabel = null;
    applyHighlight();
    renderTransitions();
    if (state.transition !== null) scrollRowIntoView(state.transition);
  }

  /* Clicking a step selects that state: the step lights up and so does every
     transition that leaves or enters it, which is what makes the diagram
     answer "what can happen here". */
  function selectState(label) {
    var same = state.stateLabel === label;
    state.stateLabel = same ? null : label;
    state.transition = null;
    applyHighlight();
    renderTransitions();
    if (state.stateLabel !== null) {
      var rows = incidentTransitions(state.stateLabel);
      if (rows.length) scrollRowIntoView(rows[0]);
    }
  }

  function clearSelection() {
    if (state.transition === null && state.stateLabel === null) return;
    state.transition = null;
    state.stateLabel = null;
    applyHighlight();
    renderTransitions();
  }

  /* Payload indices of the transitions touching *label*, in payload order. */
  function incidentTransitions(label) {
    var rows = (state.render && state.render.transitions) || [];
    var hits = [];
    rows.forEach(function (row) {
      if (row.source === label || row.target === label) hits.push(row.index);
    });
    return hits;
  }

  /* Paint the current selection onto the SVG in place; never re-renders it. */
  function applyHighlight() {
    var host = $("svg-host");
    host.querySelectorAll(".selected").forEach(function (node) {
      node.classList.remove("selected");
    });
    var indices = [];
    var labels = [];
    if (state.transition !== null) {
      indices = [state.transition];
      /* The step it leads into lights up with it. A connector names its
         target instead of reaching it, and a fork lands in another column,
         so otherwise the eye has to hunt the page for where this goes. */
      var row = transitionRow(state.transition);
      if (row && row.target) labels = [row.target];
    } else if (state.stateLabel !== null) {
      indices = incidentTransitions(state.stateLabel);
      labels = [state.stateLabel];
    }
    labels.forEach(function (label) {
      /* CSS.escape covers labels with quotes or brackets in them. */
      var selector = "[data-state=" + CSS.escape(label) + "]";
      host.querySelectorAll(selector).forEach(function (node) {
        node.classList.add("selected");
      });
    });
    indices.forEach(function (index) {
      var selector = '[data-transition="' + index + '"]';
      host.querySelectorAll(selector).forEach(function (node) {
        node.classList.add("selected");
      });
    });
  }

  /* The payload transition row carrying *index*, or null when it was dropped
     from the diagram. */
  function transitionRow(index) {
    var rows = (state.render && state.render.transitions) || [];
    for (var i = 0; i < rows.length; i += 1) {
      if (rows[i].index === index) return rows[i];
    }
    return null;
  }

  function scrollRowIntoView(index) {
    var rows = $("transition-list").querySelectorAll(".transition-row");
    var row = rows[transitionRowPosition(index)];
    if (row) row.scrollIntoView({ block: "nearest" });
  }

  /* The list is rendered in payload order, so a payload index is also its
     position - unless a row was dropped, hence the lookup rather than [index]. */
  function transitionRowPosition(index) {
    var rows = (state.render && state.render.transitions) || [];
    for (var i = 0; i < rows.length; i += 1) {
      if (rows[i].index === index) return i;
    }
    return -1;
  }

  /* Map a click on the diagram back to a payload row using the data-* the
     renderer stamped on every shape it drew. Anything else on the canvas is
     background, and clicking background clears the selection. */
  function hitTest(target) {
    var canvas = $("canvas");
    if (!target || !target.closest || !canvas.contains(target)) return;
    var link = target.closest("[data-transition]");
    if (link) {
      selectTransition(Number(link.getAttribute("data-transition")));
      return;
    }
    var step = target.closest("[data-state]");
    if (step) {
      selectState(step.getAttribute("data-state"));
      return;
    }
    clearSelection();
  }

  /* ---- source popup ---------------------------------------------------- */

  /* Right-click asks the backend for the ST behind what was hit: a step's
     branch body, or the arm a transition fires inside - a transition often
     carries actions besides the assignment, and the guard text alone hides
     them. The backend re-reads the file, so this is the code on disk now. */
  function showSourceFor(target, clientX, clientY) {
    var canvas = $("canvas");
    if (!target || !target.closest || !canvas.contains(target)) return false;
    var link = target.closest("[data-transition]");
    var step = link ? null : target.closest("[data-state]");
    if (!link && !step) return false;

    var kind = link ? "transition" : "state";
    var key = link
      ? Number(link.getAttribute("data-transition"))
      : step.getAttribute("data-state");
    /* Right-click selects too, so the diagram shows what the popup is about. */
    if (link) {
      if (state.transition !== key) selectTransition(key);
    } else if (state.stateLabel !== key) {
      selectState(key);
    }

    var path = state.selected;
    var machine = state.machine;
    openPopup(clientX, clientY, "Loading…", "", "", "");
    call("source", path, machine, kind, key).then(function (payload) {
      if (state.selected !== path || state.machine !== machine) return;
      if (failed(payload, "Could not read the source for " + path)) {
        closePopup();
        return;
      }
      openPopup(
        clientX,
        clientY,
        payload.code || "(empty)",
        payload.title,
        payload.block ? payload.subtitle : payload.subtitle + " - no action block",
        "line " + payload.line
      );
    });
    return true;
  }

  function openPopup(clientX, clientY, code, title, subtitle, line) {
    var popup = $("code-popup");
    /* Every field is user ST source: textContent, never innerHTML. */
    $("code-body").textContent = code;
    $("code-title").textContent = title || "";
    $("code-subtitle").textContent = subtitle || "";
    $("code-line").textContent = line || "";
    popup.classList.remove("hidden");

    /* Place it at the pointer, then pull it back inside the canvas so a step
       near the right or bottom edge does not open a popup half off-screen. */
    var canvas = $("canvas").getBoundingClientRect();
    var x = clientX - canvas.left + 12;
    var y = clientY - canvas.top + 12;
    popup.style.left = "0px";
    popup.style.top = "0px";
    var width = popup.offsetWidth;
    var height = popup.offsetHeight;
    popup.style.left = Math.max(4, Math.min(x, canvas.width - width - 4)) + "px";
    popup.style.top = Math.max(4, Math.min(y, canvas.height - height - 4)) + "px";
  }

  function closePopup() {
    $("code-popup").classList.add("hidden");
  }

  /* ---- zoom and pan ---------------------------------------------------- */


  function applyTransform() {
    $("svg-host").style.transform =
      "translate(" + state.panX + "px," + state.panY + "px) scale(" + state.zoom + ")";
  }

  /* Scale by `factor`, keeping the canvas point (anchorX, anchorY) still. The
     anchor is in canvas-relative pixels; omit it to zoom about the centre. */
  function setZoom(factor, anchorX, anchorY) {
    var canvas = $("canvas");
    var next = Math.min(6, Math.max(0.1, state.zoom * factor));
    if (next === state.zoom) return;
    if (anchorX === undefined) anchorX = canvas.clientWidth / 2;
    if (anchorY === undefined) anchorY = canvas.clientHeight / 2;
    /* The point under the anchor, in unscaled diagram coordinates, must land
       back under the anchor once the new scale is applied. */
    var contentX = (anchorX - state.panX) / state.zoom;
    var contentY = (anchorY - state.panY) / state.zoom;
    state.zoom = next;
    state.panX = anchorX - contentX * next;
    state.panY = anchorY - contentY * next;
    applyTransform();
  }

  function zoomToFit() {
    var svg = $("svg-host").querySelector("svg");
    var canvas = $("canvas");
    if (!svg) return;
    var width = Number(svg.getAttribute("width")) || 1;
    var height = Number(svg.getAttribute("height")) || 1;
    var pad = 24;
    var scale = Math.min(
      (canvas.clientWidth - pad) / width,
      (canvas.clientHeight - pad) / height
    );
    state.zoom = Math.min(1, Math.max(0.1, scale || 1));
    state.panX = pad / 2;
    state.panY = pad / 2;
    applyTransform();
  }

  function wireCanvas() {
    var canvas = $("canvas");
    var drag = null;
    /* A press that never moves more than this is a click on the diagram, not
       a pan; without the threshold every selection would also nudge the view. */
    var CLICK_SLOP = 4;
    canvas.addEventListener("mousedown", function (event) {
      /* The right button opens the code popup; only the left one pans. */
      if (event.button !== 0) return;
      if (event.target.closest("#code-popup")) return;
      closePopup();
      drag = {
        x: event.clientX - state.panX,
        y: event.clientY - state.panY,
        startX: event.clientX,
        startY: event.clientY,
        moved: false,
      };
      canvas.classList.add("panning");
    });
    window.addEventListener("mousemove", function (event) {
      if (!drag) return;
      if (Math.abs(event.clientX - drag.startX) > CLICK_SLOP
          || Math.abs(event.clientY - drag.startY) > CLICK_SLOP) {
        drag.moved = true;
      }
      if (!drag.moved) return;
      state.panX = event.clientX - drag.x;
      state.panY = event.clientY - drag.y;
      applyTransform();
    });
    window.addEventListener("mouseup", function (event) {
      if (drag && !drag.moved) hitTest(event.target);
      drag = null;
      canvas.classList.remove("panning");
    });
    /* Ctrl+wheel zooms about the pointer. passive:false so preventDefault can
       suppress the WebView's own page zoom. */
    canvas.addEventListener("wheel", function (event) {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      if (!event.deltaY) return;
      var rect = canvas.getBoundingClientRect();
      /* deltaMode 1 is lines and 2 is pages; normalise to a single notch. */
      var steps = event.deltaMode === 0 ? event.deltaY / 100 : event.deltaY;
      setZoom(
        Math.pow(0.85, Math.max(-4, Math.min(4, steps))),
        event.clientX - rect.left,
        event.clientY - rect.top
      );
    }, { passive: false });

    /* The WebView's own context menu has nothing to offer over a diagram, so
       it is replaced by the code popup; a right-click on empty canvas just
       closes whatever is open. */
    canvas.addEventListener("contextmenu", function (event) {
      event.preventDefault();
      if (event.target.closest("#code-popup")) return;
      if (!showSourceFor(event.target, event.clientX, event.clientY)) {
        closePopup();
      }
    });
    $("code-close").addEventListener("click", closePopup);
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closePopup();
    });
  }

  /* ---- clipboard ------------------------------------------------------- */

  function copyDiagram(field, label) {
    var payload = state.render;
    if (!payload || !payload[field]) {
      notify("There is no machine to copy.", "error");
      return;
    }
    /* navigator.clipboard is unavailable on some WebView2 configurations, and
       it rejects rather than throwing; report both outcomes. */
    if (!navigator.clipboard) {
      window.prompt("Copy the " + label + " diagram:", payload[field]);
      return;
    }
    navigator.clipboard.writeText(payload[field]).then(function () {
      notify(label + " diagram copied to the clipboard.", "success");
    }, function (error) {
      notify("Could not copy to the clipboard: "
        + String((error && error.message) || error), "error");
      window.prompt("Copy the " + label + " diagram:", payload[field]);
    });
  }

  /* ---- wiring ---------------------------------------------------------- */

  function wire() {
    $("filter").addEventListener("input", function (event) {
      state.filterText = event.target.value.toLowerCase();
      renderFiles();
    });

    $("state-filters").addEventListener("click", function (event) {
      var button = event.target.closest("[data-filter]");
      if (!button) return;
      state.filterState = button.dataset.filter;
      Array.prototype.forEach.call(
        $("state-filters").children,
        function (chip) { chip.classList.toggle("active", chip === button); }
      );
      renderFiles();
    });

    $("browse").addEventListener("click", function () {
      call("choose_workspace").then(function (chosen) {
        if (failed(chosen, "The folder dialog failed.")) return;
        if (!chosen.workspace) return;   // cancelled
        stopPolling();
        call("set_workspace", chosen.workspace).then(function (payload) {
          if (applyBootstrap(payload)) startScan();
        });
      });
    });

    $("refresh").addEventListener("click", function () {
      stopPolling();
      call("refresh_workspace").then(function (payload) {
        if (applyBootstrap(payload)) startScan();
      });
    });

    $("rescan").addEventListener("click", function () { startScan(); });

    $("stop").addEventListener("click", function () {
      if (!state.jobId) return;
      call("cancel_scan", state.jobId).then(function (payload) {
        if (failed(payload, "Could not cancel the scan.")) return;
        stopPolling();
        state.jobState = payload.state;
        $("stop").disabled = true;
        renderProgress();
      });
    });

    $("machine-select").addEventListener("change", function (event) {
      state.machine = Number(event.target.value) || 0;
      loadRender();
    });

    $("zoom-in").addEventListener("click", function () { setZoom(1.25); });
    $("zoom-out").addEventListener("click", function () { setZoom(0.8); });
    $("zoom-fit").addEventListener("click", zoomToFit);
    $("copy-mermaid").addEventListener("click", function () {
      copyDiagram("mermaid", "Mermaid");
    });
    $("copy-plantuml").addEventListener("click", function () {
      copyDiagram("plantuml", "PlantUML");
    });

    wireCanvas();
  }

  /* ---- boot ------------------------------------------------------------ */

  var booted = false;

  function boot() {
    if (booted) return;
    booted = true;
    wire();
    call("bootstrap").then(function (payload) {
      if (applyBootstrap(payload)) startScan();
    });
  }

  function bridgeReady() {
    return !!(window.pywebview && window.pywebview.api
      && window.pywebview.api.bootstrap);
  }

  /* The EdgeChromium backend injects window.pywebview before the page's own
     scripts run, so `pywebviewready` can fire before this listener exists.
     Boot from whichever signal arrives first, and never boot twice. */
  window.addEventListener("pywebviewready", boot);
  if (bridgeReady()) {
    boot();
  } else {
    var waited = 0;
    var timer = window.setInterval(function () {
      if (booted) { window.clearInterval(timer); return; }
      if (bridgeReady()) { window.clearInterval(timer); boot(); return; }
      waited += 100;
      if (waited >= 5000) {
        window.clearInterval(timer);
        notify("Could not reach the FSM bridge. Close the window and retry.",
               "error");
      }
    }, 100);
  }
})();
