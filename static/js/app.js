/* Executive Presentation Studio – browser application.
   Vanilla JavaScript; talks only to the studio's own API (see api.js). */
(function () {
  "use strict";

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var LAYOUT = window.Thumbs.LAYOUT;
  var thumb = window.Thumbs.svg;
  var STORE_KEY = "eps-draft-v1";

  var STAGES = [
    ["Understand", "Objective, audience, decision"],
    ["Structure", "Storyline and outline"],
    ["Select", "Layouts and visuals"],
    ["Generate", "Editable, on-brand slides"],
    ["Review", "Quality and evidence"],
    ["Export", "PowerPoint and briefing pack"]
  ];

  var state = {
    meta: null,
    health: null,
    files: [],            // {name, text, chars, error}
    version: "full",
    versions: {},         // version -> {title, slides, source, warning, model}
    review: null,
    reviewStale: true,
    qa: null,
    board: null,
    previewMode: false,  // slide thumbnails: icon (false) or content preview (true)
    templateFile: null,  // {template_file, name, colors} for an ad-hoc uploaded template, if any
    stages: ["todo", "todo", "todo", "todo", "todo", "todo"],
    busy: false,
    briefKey: "",         // fingerprint of the brief the versions were built from
    deck: null,           // uploaded .pptx for "Improve an existing deck": {id, name, slides, selected}
    xformResult: null
  };

  /* ------------------------------------------------------------------ helpers */
  var toastTimer;
  function toast(msg, isErr) {
    var t = $("#toast");
    t.textContent = msg;
    t.classList.toggle("err", !!isErr);
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, isErr ? 6000 : 3800);
  }
  function radio(name) { var el = $('input[name="' + name + '"]:checked'); return el ? el.value : ""; }
  function setRadio(name, value) { var el = $('input[name="' + name + '"][value="' + value + '"]'); if (el) el.checked = true; }
  function autosize(t) { t.style.height = "auto"; t.style.height = t.scrollHeight + "px"; }
  function busy(btn, on, label) {
    if (!btn) return;
    if (on) { btn.dataset.label = btn.textContent; btn.setAttribute("aria-busy", "true"); if (label) btn.textContent = label; }
    else { btn.removeAttribute("aria-busy"); if (btn.dataset.label) btn.textContent = btn.dataset.label; }
  }
  function loading(text) { return '<div class="loading"><span class="spinner" aria-hidden="true"></span>' + esc(text) + "</div>"; }

  function brief() {
    return {
      task: radio("task"),
      topic: $("#topic").value.trim(),
      decision: $("#decision").value.trim(),
      facts: $("#notesIn").value.trim(),
      audience: radio("aud"),
      length: radio("len"),
      source: radio("src"),
      template: radio("tplsrc") === "library" ? $("#tplLib").value : "",
      template_file: radio("tplsrc") === "upload" && state.templateFile ? state.templateFile.template_file : ""
    };
  }
  function briefKey(b) {
    return JSON.stringify([b.task, b.topic, b.decision, b.facts, b.audience, b.length, b.source, state.files.map(function (f) { return f.name + f.chars; })]);
  }
  function context() {
    return state.files.filter(function (f) { return !f.error && f.text; })
      .map(function (f) { return "### " + f.name + "\n" + f.text; }).join("\n\n");
  }
  function current() { return state.versions[state.version] || null; }

  /* ------------------------------------------------------------------ persistence */
  function save() {
    try {
      var b = brief();
      localStorage.setItem(STORE_KEY, JSON.stringify({
        brief: b, version: state.version, versions: state.versions, briefKey: state.briefKey, deck: state.deck,
        templateFile: state.templateFile,
        files: state.files.filter(function (f) { return !f.error; })
      }));
    } catch (e) { /* storage full or blocked: the draft simply isn't kept */ }
  }
  function restore() {
    var d = null;
    try { d = JSON.parse(localStorage.getItem(STORE_KEY) || "null"); } catch (e) { d = null; }
    if (!d || !d.brief) return false;
    var b = d.brief;
    setRadio("task", b.task || "new");
    $("#topic").value = b.topic || "";
    $("#decision").value = b.decision || "";
    $("#notesIn").value = b.facts || "";
    if (b.audience) setRadio("aud", b.audience);
    if (b.length) setRadio("len", b.length);
    if (b.source) setRadio("src", b.source);
    if (b.template) $("#tplLib").value = b.template;
    state.templateFile = d.templateFile || null;
    setRadio("tplsrc", b.template_file && state.templateFile ? "upload" : "library");
    updateTplVisibility();
    renderTplStatus();
    state.files = d.files || [];
    state.versions = d.versions || {};
    state.version = d.version || "full";
    state.briefKey = d.briefKey || "";
    state.deck = d.deck || null;
    if (current()) state.stages = ["done", "done", "done", "done", "todo", "todo"];
    return true;
  }

  /* ------------------------------------------------------------------ boot data */
  async function loadMeta() {
    var m = await Api.get("/api/meta");
    state.meta = m;
    $("#audSeg").innerHTML = m.audiences.map(function (a, i) {
      return '<label class="choice"><input type="radio" name="aud" id="aud-' + i + '" value="' + esc(a.id) + '"' + (i === 0 ? " checked" : "") + '><span>' + esc(a.short) + "</span></label>";
    }).join("");
    $("#tplLib").innerHTML = m.templates.map(function (t) {
      return '<option value="' + esc(t.id) + '"' + (t.id === m.default_template ? " selected" : "") + ">" + esc(t.name) + "</option>";
    }).join("");
  }

  /* ------------------------------------------------------------------ template picker */
  function updateTplVisibility() {
    var upload = radio("tplsrc") === "upload";
    $("#tplLib").hidden = upload;
    $("#tplDrop").hidden = !upload;
  }
  function renderTplStatus() {
    var t = state.templateFile;
    $("#tplStatus").innerHTML = t
      ? 'Using <b>' + esc(t.name) + '</b>' + (t.colors && t.colors.accent ? ' <span class="swatch" style="background:#' + esc(t.colors.accent) + '"></span>' : "")
      : "";
  }

  async function loadHealth() {
    var pill = $("#modelPill"), foot = $("#railFoot");
    try {
      var h = await Api.get("/api/health");
      state.health = h;
      var on = h.llm.enabled && h.llm.reachable;
      if (h.pdf) { $("#files").setAttribute("accept", ".pptx,.docx,.xlsx,.pdf,.csv,.txt,.md"); $("#fileTypes").textContent = ".pptx .docx .xlsx .pdf .csv .txt .md"; }
      var eng = h.pptx || {};
      var engLine = "<br>PowerPoint: <b>" + esc(eng.engine || "?") + "</b>" + (eng.advanced ? "" : " (install python-pptx for templates and charts)");
      pill.innerHTML = '<span class="led ' + (on ? "on" : "off") + '"></span>Powered by ARIF';
      pill.title = on ? "ARIF is connected" : (h.llm.detail || "ARIF is not reachable");
      foot.innerHTML = '<span class="led ' + (on ? "on" : "off") + '"></span> Powered by ARIF' + engLine;
      renderXform();
    } catch (e) {
      pill.innerHTML = '<span class="led off"></span>Server unreachable';
      foot.textContent = "Cannot reach the studio server. Check that it is running.";
    }
  }

  function audienceLabel(id) {
    var a = state.meta && state.meta.audiences.filter(function (x) { return x.id === id; })[0];
    return a ? a.label : id;
  }

  /* ------------------------------------------------------------------ pipeline */
  function renderPipeline() {
    $("#pipeline").innerHTML = STAGES.map(function (s, i) {
      return '<div class="stage" data-s="' + state.stages[i] + '"><div class="bar"><i></i></div><b>' + s[0] + "</b><small>" + s[1] + "</small></div>";
    }).join("");
  }
  function setStage(i, s) { state.stages[i] = s; renderPipeline(); }

  /* ------------------------------------------------------------------ storyline */
  function renderDeck() {
    var v = current();
    var b = brief();
    var eyebrow = { full: "Storyline", summary: "Executive summary version", brief: "Decision brief version" }[state.version];
    if (!v) {
      $("#deckEyebrow").textContent = "No storyline yet";
      $("#deckTitle").textContent = state.busy ? "Building your storyline…" : "Your storyline will appear here";
      $("#deckMeta").innerHTML = "";
      $("#panel-story").innerHTML = state.busy ? loading("Drafting the storyline. This can take up to a minute.") :
        '<p class="empty">Fill in the brief and select “Design my presentation”. The AI drafts an answer-first storyline with an action title, layout and visual for every slide. It only uses figures you provide and marks anything that still needs evidence.</p>';
      $("#qaCount").hidden = true;
      $("#exportNote").textContent = "Generate a storyline first.";
      return;
    }
    $("#deckEyebrow").textContent = eyebrow;
    $("#deckTitle").textContent = v.title || b.topic;
    var srcChip = v.source === "llm"
      ? '<span class="chip ok" title="Generated by the AI model">AI · ' + esc(v.model || "LLM") + "</span>"
      : '<span class="chip warn" title="' + esc(v.warning || "") + '">Built-in rules</span>';
    $("#deckMeta").innerHTML = [
      '<span class="chip acc">' + esc(audienceLabel(b.audience)) + "</span>",
      '<span class="chip num">' + v.slides.length + " slide" + (v.slides.length === 1 ? "" : "s") + "</span>",
      srcChip
    ].join("");

    $("#panel-story").innerHTML =
      '<div class="slideview" role="radiogroup" aria-label="Slide display">' +
        '<button type="button" data-view="icon" aria-pressed="' + !state.previewMode + '">Icons</button>' +
        '<button type="button" data-view="preview" aria-pressed="' + state.previewMode + '">Preview</button>' +
      "</div>" +
      '<ol class="slides' + (state.previewMode ? " preview" : "") + '">' + v.slides.map(function (s, i) {
      var ev = s.evidence || {};
      var linked = ev.status === "linked";
      return '<li class="slide-row" data-i="' + i + '">' +
        '<span class="n num">' + String(i + 1).padStart(2, "0") + "</span>" +
        (state.previewMode ? window.Thumbs.preview(s) : thumb(s.kind)) +
        '<div class="body">' +
          '<textarea class="headline" rows="1" id="h-' + i + '" data-f="headline" aria-label="Headline for slide ' + (i + 1) + '">' + esc(s.headline) + "</textarea>" +
          '<div class="tags"><span class="chip">' + esc(LAYOUT[s.kind] || s.kind) + "</span>" + (s.visual ? '<span class="chip">' + esc(s.visual) + "</span>" : "") + (s.chart ? '<span class="chip acc">Native chart · ' + s.chart.series.length + " series</span>" : "") + "</div>" +
          "<details><summary>Content and speaker notes</summary><div class=\"detail-grid\">" +
            '<label for="b-' + i + '">Slide content, one point per line<textarea class="text" rows="' + Math.max(3, (s.body || []).length + 1) + '" id="b-' + i + '" data-f="body">' + esc((s.body || []).join("\n")) + "</textarea></label>" +
            '<label for="n-' + i + '">Speaker notes<textarea class="text" rows="3" id="n-' + i + '" data-f="notes">' + esc(s.notes || "") + "</textarea></label>" +
            '<label for="e-' + i + '">Evidence source<input class="text" id="e-' + i + '" data-f="source" value="' + esc(ev.source || "") + '" placeholder="e.g. Finance cube, Sep close"></label>' +
            '<label for="c-' + i + '">Chart data (creates a native, editable chart)<textarea class="text" rows="3" id="c-' + i + '" data-f="chart" placeholder="Q1, Q2, Q3&#10;Plan: 110, 118, 125&#10;Actual: 108, 121, 130">' + esc(chartToText(s.chart)) + '</textarea><span class="chartnote" id="cn-' + i + '">First line: categories. Then one line per series: name, then values.</span></label>' +
          "</div></details>" +
        "</div>" +
        '<div><div class="status">' + (linked ? '<span class="dot"></span>Evidence linked' : '<span class="dot warn"></span>' + esc(ev.gap || "Evidence needed")) + "</div>" +
        '<div class="slide-actions">' +
          '<button type="button" class="icon-btn" data-act="sharpen" title="Rewrite the headline as an executive action title">Sharpen</button>' +
          '<button type="button" class="icon-btn" data-act="up" aria-label="Move slide up"' + (i === 0 ? " disabled" : "") + ">↑</button>" +
          '<button type="button" class="icon-btn" data-act="down" aria-label="Move slide down"' + (i === v.slides.length - 1 ? " disabled" : "") + ">↓</button>" +
          '<button type="button" class="icon-btn" data-act="del" aria-label="Remove slide">Remove</button>' +
        "</div></div>" +
      "</li>";
    }).join("") + "</ol>";
    $$(".headline").forEach(autosize);
    renderReview();
  }

  function markEdited() {
    state.reviewStale = true;
    state.qa = null;
    save();
  }

  $("#panel-story").addEventListener("input", function (e) {
    var row = e.target.closest(".slide-row"); if (!row) return;
    var s = current().slides[+row.dataset.i];
    var f = e.target.dataset.f;
    if (f === "headline") { s.headline = e.target.value; autosize(e.target); }
    else if (f === "body") s.body = e.target.value.split("\n").map(function (x) { return x.trim(); }).filter(Boolean);
    else if (f === "notes") s.notes = e.target.value;
    else if (f === "chart") {
      var note = $("#cn-" + row.dataset.i);
      var parsed = textToChart(e.target.value);
      if (parsed.chart) { s.chart = parsed.chart; note.textContent = "Chart ready: " + parsed.chart.series.length + " series × " + parsed.chart.categories.length + " categories."; note.className = "chartnote"; }
      else { delete s.chart; note.textContent = parsed.error || "First line: categories. Then one line per series: name, then values."; note.className = "chartnote" + (parsed.error ? " err" : ""); }
    }
    else if (f === "source") {
      s.evidence = s.evidence || {};
      s.evidence.source = e.target.value.trim();
      s.evidence.status = s.evidence.source ? "linked" : "needed";
      var st = $(".status", row);
      st.innerHTML = s.evidence.status === "linked" ? '<span class="dot"></span>Evidence linked' : '<span class="dot warn"></span>' + esc(s.evidence.gap || "Evidence needed");
    }
    markEdited();
  });

  $("#panel-story").addEventListener("click", async function (e) {
    var view = e.target.closest("button[data-view]");
    if (view) { state.previewMode = view.dataset.view === "preview"; renderDeck(); return; }
    var btn = e.target.closest("button[data-act]"); if (!btn) return;
    var i = +btn.closest(".slide-row").dataset.i;
    var slides = current().slides;
    var act = btn.dataset.act;
    if (act === "up" && i > 0) { slides.splice(i - 1, 0, slides.splice(i, 1)[0]); }
    else if (act === "down" && i < slides.length - 1) { slides.splice(i + 1, 0, slides.splice(i, 1)[0]); }
    else if (act === "del") { slides.splice(i, 1); toast("Slide removed."); }
    else if (act === "sharpen") {
      busy(btn, true, "…");
      try {
        var r = await Api.post("/api/sharpen", { headline: slides[i].headline, body: slides[i].body, brief: brief() });
        if (r.headline && r.headline !== slides[i].headline) { slides[i].headline = r.headline; toast(r.source === "llm" ? "Headline rewritten." : "AI unavailable: headline tidied with built-in rules."); }
        else toast("That headline already reads as an action title.");
      } catch (err) { toast(err.message, true); }
      busy(btn, false);
    }
    markEdited();
    renderDeck();
  });

  /* ------------------------------------------------------------------ chart data text */
  function chartToText(ch) {
    if (!ch) return "";
    return [ch.categories.join(", ")].concat(ch.series.map(function (x) { return x.name + ": " + x.values.join(", "); })).join("\n");
  }
  function textToChart(text) {
    var lines = text.split("\n").map(function (l) { return l.trim(); }).filter(Boolean);
    if (!lines.length) return {};
    if (lines.length < 2) return { error: "Add at least one series line, e.g. “Actual: 108, 121, 130”." };
    var cats = lines[0].split(",").map(function (x) { return x.trim(); }).filter(Boolean);
    var series = [];
    for (var i = 1; i < lines.length; i++) {
      var m = /^([^:]+):(.*)$/.exec(lines[i]);
      if (!m) return { error: "Line " + (i + 1) + " needs a series name followed by a colon." };
      var vals = m[2].split(",").map(function (x) { return x.trim().replace(/[%$]/g, ""); }).filter(function (x) { return x !== ""; });
      if (vals.length !== cats.length) return { error: "“" + m[1].trim() + "” has " + vals.length + " values but there are " + cats.length + " categories." };
      var nums = vals.map(Number);
      if (nums.some(isNaN)) return { error: "“" + m[1].trim() + "” contains a value that isn't a number." };
      series.push({ name: m[1].trim(), values: nums });
    }
    return { chart: { type: "column", title: "", categories: cats, series: series } };
  }

  /* ------------------------------------------------------------------ improve an existing deck */
  function renderXform() {
    var panel = $("#xform");
    panel.hidden = radio("task") !== "improve";
    if (panel.hidden) return;
    var d = state.deck, body = $("#xformBody");
    var canTransform = !state.health || !state.health.pptx || state.health.pptx.transform;
    if (!d) {
      $("#xformTitle").textContent = "Upload the deck you want to improve";
      $("#xformNote").textContent = "Add a .pptx under Content source. You can then rewrite selected slides in place, or move them onto the corporate template.";
      body.hidden = true;
      return;
    }
    $("#xformTitle").textContent = d.name;
    if (!d.id || !canTransform) {
      $("#xformNote").textContent = "Slide-by-slide transformation needs python-pptx on the server. You can still select “Restructure my presentation” to build a new storyline from this deck’s content.";
      body.hidden = true;
      return;
    }
    $("#xformNote").textContent = "Pick the slides to work on. To build a completely new storyline from this deck instead, select “Restructure my presentation”.";
    body.hidden = false;
    $("#xslides").innerHTML = d.slides.map(function (sl) {
      var tags = [];
      if (sl.charts) tags.push('<span class="chip">Chart ×' + sl.charts + "</span>");
      if (sl.tables) tags.push('<span class="chip">Table ×' + sl.tables + "</span>");
      if (sl.pictures) tags.push('<span class="chip">Picture ×' + sl.pictures + "</span>");
      if (sl.other) tags.push('<span class="chip warn" title="Not carried over when moving onto the template">Diagram ×' + sl.other + "</span>");
      var checked = d.selected.indexOf(sl.index) >= 0;
      return '<li><label><input type="checkbox" id="xs-' + sl.index + '" data-x="' + sl.index + '"' + (checked ? " checked" : "") + '>' +
        '<span class="n num">' + String(sl.index).padStart(2, "0") + '</span><span class="t">' + esc(sl.title || "(no title)") +
        "<small>" + esc((sl.body || [])[0] || sl.layout) + "</small>" + (tags.length ? '<span class="tags">' + tags.join("") + "</span>" : "") + "</span></label></li>";
    }).join("");
    updateXformCount();
    renderXformReport();
  }
  function updateXformCount() {
    var d = state.deck; if (!d) return;
    $("#xformCount").textContent = d.selected.length + " of " + d.slides.length + " slides selected";
    var tpl = $("#xa-tpl").checked;
    $("#xformMode").textContent = tpl ? "The new deck will contain only the selected slides, on the approved template."
      : "All slides are kept; only the selected ones change. Formatting is preserved.";
  }
  $("#xslides").addEventListener("change", function (e) {
    var n = +e.target.dataset.x; if (!n) return;
    var sel = state.deck.selected;
    if (e.target.checked) { if (sel.indexOf(n) < 0) sel.push(n); } else sel.splice(sel.indexOf(n), 1);
    sel.sort(function (a, b) { return a - b; });
    updateXformCount(); save();
  });
  $("#selAll").addEventListener("click", function () { state.deck.selected = state.deck.slides.map(function (x) { return x.index; }); renderXform(); save(); });
  $("#selNone").addEventListener("click", function () { state.deck.selected = []; renderXform(); save(); });
  $("#xa-tpl").addEventListener("change", updateXformCount);

  $("#xformGo").addEventListener("click", async function () {
    var d = state.deck;
    if (!d.selected.length) { toast("Select at least one slide.", true); return; }
    var actions = { headlines: $("#xa-head").checked, simplify: $("#xa-simp").checked, retemplate: $("#xa-tpl").checked };
    if (!actions.headlines && !actions.simplify && !actions.retemplate) { toast("Choose at least one change to make.", true); return; }
    var btn = this; busy(btn, true, "Transforming " + d.selected.length + " slide" + (d.selected.length > 1 ? "s" : "") + "…");
    $("#xformReport").innerHTML = loading("Working through the slides. Large decks can take a minute.");
    try {
      state.xformResult = await Api.post("/api/deck/transform", { deck_id: d.id, selected: d.selected, actions: actions, brief: brief() });
      renderXformReport();
      await Api.download("/api/download/" + state.xformResult.file_id, null, state.xformResult.filename);
      toast("Downloaded " + state.xformResult.filename + ".");
    } catch (e) {
      $("#xformReport").innerHTML = '<p class="empty">' + esc(e.message) + "</p>";
      toast(e.message, true);
    }
    busy(btn, false);
  });

  function renderXformReport() {
    var r = state.xformResult, box = $("#xformReport");
    if (!r) { box.innerHTML = ""; return; }
    box.innerHTML = '<div class="report-head"><span><b>Change report</b> <span class="note">' + esc(r.note) +
      (r.source === "rules" ? " AI unavailable: built-in rules were used." : "") + '</span></span><button type="button" class="btn btn-ghost" id="xformDl">Download again</button></div>' +
      '<ol class="xreport">' + r.report.map(function (x) {
        var changed = x.after && x.after !== x.before;
        return '<li><span class="n num">' + String(x.index).padStart(2, "0") + "</span><div>" +
          (changed ? '<div class="before">' + esc(x.before) + '</div><div class="after">' + esc(x.after) + "</div>" : '<div class="after">' + esc(x.before || "(no title)") + "</div>") +
          "<ul>" + x.changes.map(function (c) { return "<li>" + esc(c) + "</li>"; }).join("") +
          x.warnings.map(function (w) { return '<li class="warn-li">' + esc(w) + "</li>"; }).join("") + "</ul></div></li>";
      }).join("") + "</ol>";
  }
  $("#xformReport").addEventListener("click", async function (e) {
    if (e.target.id !== "xformDl") return;
    try { await Api.download("/api/download/" + state.xformResult.file_id, null, state.xformResult.filename); }
    catch (err) { toast(err.message, true); }
  });

  /* ------------------------------------------------------------------ generate */
  async function generate(version, opts) {
    opts = opts || {};
    var b = brief();
    var err = $("#briefError");
    if (!b.topic) { err.textContent = "Add a presentation topic so the AI knows what to build."; err.hidden = false; $("#topic").focus(); return; }
    err.hidden = true;
    if (state.busy) return;

    var key = briefKey(b);
    if (key !== state.briefKey) { state.versions = {}; state.briefKey = key; }
    state.busy = true;
    state.review = null; state.qa = null; state.board = null; state.reviewStale = true;
    var go = $("#go"); busy(go, true, "Working…");
    state.stages = ["run", "todo", "todo", "todo", "todo", "todo"]; renderPipeline();
    delete state.versions[version];
    renderDeck();

    try {
      setStage(0, "done"); setStage(1, "run");
      var r = await Api.post("/api/storyline", { brief: b, version: version, context: context() });
      state.versions[version] = r;
      setStage(1, "done"); setStage(2, "done"); setStage(3, "done");
      state.busy = false;
      renderDeck();
      if (r.source !== "llm" && r.warning) toast(r.warning, true);
      await runReview();
      save();
      if (!opts.quiet) toast("Storyline ready. Edit any headline, then check quality and export.");
    } catch (e2) {
      state.busy = false;
      var idx = state.stages.indexOf("run"); if (idx >= 0) setStage(idx, "fail");
      renderDeck();
      toast(e2.message, true);
    }
    busy(go, false);
  }

  /* ------------------------------------------------------------------ review */
  async function runReview() {
    var v = current(); if (!v) return;
    setStage(4, "run");
    $("#panel-qa").innerHTML = loading("Running the quality check…");
    try {
      state.review = await Api.post("/api/review", { brief: brief(), slides: v.slides });
      state.reviewStale = false;
      setStage(4, "done");
    } catch (e) {
      state.review = null;
      setStage(4, "fail");
      toast(e.message, true);
    }
    renderReview();
  }

  function renderReview() {
    var v = current(), panel = $("#panel-qa"), cnt = $("#qaCount");
    if (!v) { panel.innerHTML = '<p class="empty">The quality check runs after the storyline is generated.</p>'; cnt.hidden = true; return; }
    var r = state.review;
    if (!r) { panel.innerHTML = '<div class="panel-bar"><span class="note">The quality check has not run on this version.</span><button class="btn btn-ghost" type="button" id="rerun">Run quality check</button></div>'; cnt.hidden = true; return; }
    var flags = r.checks.filter(function (c) { return !c.ok; }).length;
    var passed = r.checks.length - flags;
    panel.innerHTML =
      '<div class="score"><span class="big num">' + passed + "/" + r.checks.length + '</span><div style="flex:1 1 200px"><div class="eyebrow" style="margin-bottom:6px">Executive readiness</div><div class="meter"><i style="width:' + Math.round(passed / r.checks.length * 100) + '%"></i></div></div>' +
      (state.reviewStale ? '<button class="btn btn-ghost" type="button" id="rerun">Re-run after your edits</button>' : "") + "</div>" +
      '<ul class="checks">' + r.checks.map(function (c) {
        return '<li><span class="ico ' + (c.ok ? "" : "warn") + '" aria-hidden="true">' + (c.ok ? "✓" : "!") + "</span><div><b>" + esc(c.title) + "</b><span>" + esc(c.detail) + "</span></div></li>";
      }).join("") + "</ul>";
    cnt.hidden = false;
    cnt.textContent = flags ? flags + " to fix" : "ready";
    cnt.className = "count" + (flags ? "" : " ok");
    $("#exportNote").textContent = flags
      ? flags + " quality check" + (flags > 1 ? "s are" : " is") + " still open. You can export now and finish in PowerPoint, or resolve them here first."
      : "All quality checks pass.";
  }
  $("#panel-qa").addEventListener("click", function (e) { if (e.target.id === "rerun") runReview(); });

  /* ------------------------------------------------------------------ Q&A prep */
  async function loadQA(force) {
    var v = current(), panel = $("#panel-prep");
    if (!v) { panel.innerHTML = '<p class="empty">Generate a storyline first. The AI then anticipates the hardest questions your audience is likely to ask.</p>'; return; }
    if (state.qa && !force) return renderQA();
    panel.innerHTML = loading("Anticipating questions from " + audienceLabel(brief().audience) + "…");
    try {
      state.qa = await Api.post("/api/qa", { brief: brief(), slides: v.slides });
      renderQA();
    } catch (e) {
      panel.innerHTML = '<p class="empty">' + esc(e.message) + "</p>";
    }
  }
  function renderQA() {
    var q = state.qa;
    $("#panel-prep").innerHTML =
      '<div class="panel-bar"><span class="note">' + (q.source === "llm" ? "Generated by " + esc(q.model || "the AI model") : "Built-in question set (AI unavailable)") + '</span><button class="btn btn-ghost" type="button" id="reqa">Regenerate</button></div>' +
      '<ul class="qa">' + q.questions.map(function (x) {
        return '<li><span class="eyebrow">Likely question</span><span class="q">' + esc(x.question) + '</span><span class="a">' + esc(x.answer) + '</span><span class="ev">Evidence: ' + esc(x.evidence || "–") + "</span></li>";
      }).join("") + "</ul>";
  }
  $("#panel-prep").addEventListener("click", function (e) { if (e.target.id === "reqa") loadQA(true); });

  /* ------------------------------------------------------------------ board assessment */
  var RESULT_CLASS = { "PASS": "ok", "FAIL": "crit", "WARNING": "warn", "NOT VERIFIABLE": "", "NOT APPLICABLE": "na" };
  function boardContext() {
    return {
      presentation_type: $("#bc-type").value, stage_gate: $("#bc-gate").value, ook_investment: $("#bc-ook").value,
      submission_date: $("#bc-sub").value, meeting_date: $("#bc-meet").value,
    };
  }
  async function runBoardAssessment() {
    var v = current(); if (!v) return;
    var panel = $("#boardResult"), btn = $("#boardGo");
    busy(btn, true, "Assessing…");
    panel.innerHTML = loading("Checking the GEC/GIC checklist and scoring board readiness…");
    try {
      state.board = await Api.post("/api/board-assessment", { brief: brief(), slides: v.slides, context: boardContext() });
    } catch (e) {
      state.board = null;
      panel.innerHTML = '<p class="empty">' + esc(e.message) + "</p>";
      busy(btn, false);
      return;
    }
    renderBoard();
    busy(btn, false);
  }
  function renderBoard() {
    var v = current(), panel = $("#boardResult"), cnt = $("#boardCount");
    if (!v) { panel.innerHTML = '<p class="empty">Generate a storyline first, then check it against the GEC/GIC checklist here.</p>'; cnt.hidden = true; return; }
    var r = state.board;
    if (!r) {
      panel.innerHTML = '<p class="empty">Set any context you know (optional) and select “Run board assessment” to check this storyline against the GEC/GIC checklist and score its board readiness.</p>';
      cnt.hidden = true;
      return;
    }
    var fails = r.compliance.filter(function (c) { return c.result === "FAIL"; }).length;
    cnt.hidden = false;
    cnt.textContent = fails ? fails + " fail" + (fails > 1 ? "s" : "") : "checked";
    cnt.className = "count" + (fails ? "" : " ok");

    var scored = r.board_readiness.filter(function (d) { return d.score != null; });
    var avg = scored.length ? scored.reduce(function (s, d) { return s + d.score; }, 0) / scored.length : null;

    var cats = [];
    r.compliance.forEach(function (c) { if (cats.indexOf(c.category) < 0) cats.push(c.category); });

    var html = '<div class="panel-bar"><span class="note">' +
      (r.source === "llm" ? "Assessed by " + esc(r.model || "the AI model") : "Built-in structural checks only (AI unavailable) — title quality and board readiness need the AI model") +
      '</span><button class="btn btn-ghost" type="button" id="reboard">Re-run</button></div>';
    if (r.warning) html += '<p class="note" style="padding:6px 20px 0">' + esc(r.warning) + "</p>";
    if (r.summary) html += '<p class="note" style="padding:10px 20px 0;max-width:80ch">' + esc(r.summary) + "</p>";

    html += '<div class="ready"><div class="eyebrow">Board readiness' + (avg != null ? " · " + avg.toFixed(1) + "/5" : "") + "</div>" +
      r.board_readiness.map(function (d) {
        var pct = d.score != null ? Math.round(d.score / 5 * 100) : 0;
        return '<div class="ready-row"><span class="rlabel">' + esc(d.label) + '</span><div class="rmeter"><i style="width:' + pct + '%"></i></div>' +
          '<span class="rscore">' + (d.score != null ? d.score + "/5" : "–") + "</span>" +
          (d.comment ? '<p class="rcomment">' + esc(d.comment) + "</p>" : "") + "</div>";
      }).join("") + "</div>";

    html += cats.map(function (cat) {
      var items = r.compliance.filter(function (c) { return c.category === cat; });
      return '<div class="board-cat">' + esc(cat) + '</div><ul class="board-list">' + items.map(function (c) {
        var cls = RESULT_CLASS[c.result] || "";
        return '<li><div class="bid"><span class="chip ' + cls + '">' + esc(c.result) + '</span><span class="rid">' + esc(c.id) + '</span></div><div>' +
          '<span class="req">' + esc(c.requirement) + (c.critical ? '<span class="crit-mark">Critical</span>' : "") + "</span>" +
          (c.evidence ? '<span class="ev">' + esc(c.evidence) + "</span>" : "") +
          (c.action ? '<span class="act">Action: ' + esc(c.action) + "</span>" : "") + "</div></li>";
      }).join("") + "</ul>";
    }).join("");

    panel.innerHTML = html;
  }
  $("#panel-board").addEventListener("click", function (e) { if (e.target.id === "reboard") runBoardAssessment(); });
  $("#boardCtxForm").addEventListener("submit", function (e) { e.preventDefault(); runBoardAssessment(); });

  /* ------------------------------------------------------------------ tabs */
  function selectTab(name) {
    $$(".tabs button").forEach(function (x) { x.setAttribute("aria-selected", String(x.dataset.tab === name)); });
    ["story", "qa", "prep", "board", "export"].forEach(function (t) { $("#panel-" + t).hidden = t !== name; });
    if (name === "qa" && current() && (!state.review || state.reviewStale) && !state.busy) runReview();
    if (name === "prep") loadQA(false);
    if (name === "board") renderBoard();
  }
  $$(".tabs button").forEach(function (b) { b.addEventListener("click", function () { selectTab(b.dataset.tab); }); });

  /* ------------------------------------------------------------------ export */
  $("#exportBtn").addEventListener("click", async function () {
    var v = current();
    if (!v) { toast("Generate a storyline first.", true); return; }
    var btn = this; busy(btn, true, "Preparing files…");
    setStage(5, "run");
    var b = brief();
    try {
      var name = await Api.download("/api/export/pptx", { brief: b, title: v.title, slides: v.slides }, "presentation.pptx");
      var want = { notes: $("#x-notes").checked, brief: $("#x-brief").checked, qa: $("#x-qa").checked };
      if (want.notes || want.brief || want.qa) {
        if (want.qa && !state.qa) { try { state.qa = await Api.post("/api/qa", { brief: b, slides: v.slides }); } catch (e) { /* pack goes without Q&A */ } }
        await Api.download("/api/export/briefing", { brief: b, title: v.title, slides: v.slides, include: want, qa: state.qa ? state.qa.questions : [] }, "briefing.md");
        toast("Downloaded " + name + " and the briefing pack.");
      } else toast("Downloaded " + name + ".");
      setStage(5, "done");
    } catch (e) {
      setStage(5, "fail");
      toast(e.message, true);
    }
    busy(btn, false);
  });

  /* ------------------------------------------------------------------ brief form */
  $("#briefForm").addEventListener("submit", function (e) {
    e.preventDefault();
    if (radio("task") === "find") { show("repo"); return; }
    generate("full");
  });

  $("#briefForm").addEventListener("change", function (e) {
    var t = e.target;
    if (t.name === "task") {
      var labels = { "new": "Design my presentation", improve: "Restructure my presentation", single: "Design my slide", find: "Open slide repository" };
      $("#go").textContent = labels[t.value];
      $("#lenField").hidden = t.value === "single";
      if (t.value === "improve") { setRadio("src", "deck"); $("#dropzone").hidden = false; }
      renderXform();
    }
    if (t.name === "src") $("#dropzone").hidden = t.value === "scratch" && state.files.length === 0;
    if (t.name === "tplsrc") updateTplVisibility();
    if (t.id !== "files" && t.id !== "tplFile") save();
  });
  $("#briefForm").addEventListener("input", function (e) { if (e.target.classList.contains("text")) save(); });

  $("#files").addEventListener("change", async function (e) {
    var list = Array.prototype.slice.call(e.target.files);
    e.target.value = "";
    for (var i = 0; i < list.length; i++) {
      var f = list[i];
      var entry = { name: f.name, text: "", chars: 0, error: "", pending: true };
      state.files.push(entry);
      renderFiles();
      try {
        var isDeck = /\.pptx$/i.test(f.name);
        var r = isDeck ? await Api.uploadDeck(f) : await Api.upload(f);
        entry.text = r.text; entry.chars = r.chars;
        if (r.truncated) entry.note = "trimmed";
        if (isDeck) {
          state.deck = { id: r.deck_id, name: r.name, slides: r.slides, selected: r.slides.map(function (x) { return x.index; }) };
          state.xformResult = null;
          entry.slides = r.slides.length;
          renderXform();
        }
      } catch (err) { entry.error = err.message; }
      entry.pending = false;
      renderFiles();
    }
    save();
  });

  $("#tplFile").addEventListener("change", async function (e) {
    var f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    $("#tplStatus").textContent = "Uploading " + f.name + "…";
    try {
      state.templateFile = await Api.uploadTemplate(f);
      renderTplStatus();
      toast("Using " + state.templateFile.name + " as the template.");
    } catch (err) {
      state.templateFile = null;
      $("#tplStatus").innerHTML = '<span class="err">' + esc(err.message) + "</span>";
    }
    save();
  });

  function renderFiles() {
    $("#fileList").innerHTML = state.files.map(function (f, i) {
      var status = f.pending ? "Reading…" : f.error ? '<span class="err">' + esc(f.error) + "</span>" :
        (f.slides ? f.slides + " slides · " : "") + (f.chars.toLocaleString() + " characters" + (f.note ? " (trimmed)" : ""));
      return '<li><span title="' + esc(f.name) + '">' + esc(f.name) + "</span><span>" + status + ' <button type="button" data-rm="' + i + '" aria-label="Remove ' + esc(f.name) + '">✕</button></span></li>';
    }).join("");
  }
  $("#fileList").addEventListener("click", function (e) {
    var b = e.target.closest("[data-rm]"); if (!b) return;
    var removed = state.files.splice(+b.dataset.rm, 1)[0];
    if (removed && state.deck && removed.name === state.deck.name) { state.deck = null; state.xformResult = null; renderXform(); }
    renderFiles(); save();
  });

  $("#newDeck").addEventListener("click", function () {
    $("#briefForm").reset();
    $("#topic").value = ""; $("#decision").value = ""; $("#notesIn").value = "";
    state.files = []; state.versions = {}; state.briefKey = ""; state.review = null; state.qa = null; state.board = null; state.version = "full";
    state.deck = null; state.xformResult = null; state.templateFile = null;
    state.stages = ["todo", "todo", "todo", "todo", "todo", "todo"];
    $("#dropzone").hidden = true; $("#lenField").hidden = false; $("#go").textContent = "Design my presentation";
    $("#tplStatus").textContent = ""; updateTplVisibility();
    renderFiles(); renderPipeline(); renderDeck(); renderXform(); selectTab("story"); save();
    $("#topic").focus();
  });

  /* ------------------------------------------------------------------ navigation */
  function show(v) {
    $$("main > section").forEach(function (s) { s.hidden = s.id !== "view-" + v; });
    $$(".rail button").forEach(function (b) { if (b.dataset.view === v) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); });
    try { localStorage.setItem("eps-view", v); } catch (e) { /* ignore */ }
    if (v === "repo" && !repoLoaded) loadRepo();
    window.scrollTo(0, 0);
  }
  $$(".rail button").forEach(function (b) { b.addEventListener("click", function () { show(b.dataset.view); }); });

  function addSlide(slide, label) {
    var v = current();
    if (!v) {
      var b = brief();
      v = state.versions[state.version] = { title: b.topic || "Untitled presentation", slides: [], source: "manual" };
      state.stages = ["done", "done", "done", "done", "todo", "todo"];
      renderPipeline();
    }
    v.slides.push(slide);
    markEdited();
    renderDeck();
    show("studio");
    selectTab("story");
    toast("Added “" + label + "” as slide " + v.slides.length + ".");
  }

  /* ------------------------------------------------------------------ advisor */
  async function advise(text) {
    if (!text.trim()) { toast("Describe the message you want the slide to communicate.", true); return; }
    var btn = $("#adviseBtn"); busy(btn, true, "Thinking…");
    $("#rec").innerHTML = loading("Matching your message to the right slide…");
    $("#alts").innerHTML = "";
    try {
      var r = await Api.post("/api/advise", { message: text, brief: brief() });
      var m = r.primary;
      $("#rec").innerHTML =
        "<div>" + thumb(m.kind) + "</div>" +
        '<div style="min-width:0"><span class="eyebrow">Recommended layout' + (r.source === "llm" ? "" : " · built-in rules") + "</span><h2>" + esc(m.name) + '</h2><p class="why">' + esc(m.why) + "</p>" +
        "<ol>" + (m.steps || []).map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("") + "</ol>" +
        '<div class="sample"><span class="eyebrow">Example headline</span>' + esc(m.example) + "</div>" +
        '<div class="row" style="margin-top:14px"><button class="btn btn-primary" type="button" id="useRec">Add to my deck</button></div></div>';
      $("#alts").innerHTML = (r.alternates || []).map(function (a) {
        return '<div class="panel alt">' + thumb(a.kind) + '<div><span class="eyebrow">Also consider</span><br><b>' + esc(a.name) + "</b><p>" + esc(a.why) + "</p></div></div>";
      }).join("");
      $("#useRec").onclick = function () {
        addSlide({ kind: m.kind, headline: m.example, body: (m.steps || []).slice(), visual: m.name, notes: "", evidence: { status: "needed", gap: "Add supporting data", source: "" } }, m.name);
      };
    } catch (e) {
      $("#rec").innerHTML = '<p class="empty">' + esc(e.message) + "</p>";
    }
    busy(btn, false);
  }
  $("#adviseForm").addEventListener("submit", function (e) { e.preventDefault(); advise($("#message").value); });
  $$(".examples button").forEach(function (b) { b.addEventListener("click", function () { $("#message").value = b.textContent; advise(b.textContent); }); });

  /* ------------------------------------------------------------------ repository */
  var repo = [], repoCat = "All", repoLoaded = false;
  async function loadRepo() {
    $("#repoGrid").innerHTML = loading("Loading approved slides…");
    try { repo = (await Api.get("/api/repository")).items; repoLoaded = true; renderRepo(); }
    catch (e) { $("#repoGrid").innerHTML = '<p class="empty">' + esc(e.message) + "</p>"; }
  }
  function renderRepo() {
    var cats = ["All"].concat(repo.map(function (r) { return r.category; }).filter(function (c, i, a) { return a.indexOf(c) === i; }));
    var q = $("#repoSearch").value.toLowerCase().trim();
    var list = repo.filter(function (r) {
      return (repoCat === "All" || r.category === repoCat) &&
        (!q || [r.title, r.question, r.category, LAYOUT[r.kind] || ""].join(" ").toLowerCase().indexOf(q) >= 0);
    });
    $("#repoFilters").innerHTML = cats.map(function (c) { return '<button type="button" aria-pressed="' + (c === repoCat) + '">' + esc(c) + "</button>"; }).join("");
    $("#repoGrid").innerHTML = list.length ? list.map(function (r) {
      return '<article class="panel repo-card">' + thumb(r.kind) +
        '<div><span class="eyebrow">' + esc(r.category) + " · " + esc(LAYOUT[r.kind] || r.kind) + "</span><h3>" + esc(r.title) + '</h3><div class="q">Answers: ' + esc(r.question) + "</div></div>" +
        '<div class="foot"><span class="chip num">Reused ' + (r.uses || 0) + '×</span><button class="btn btn-ghost" type="button" data-id="' + esc(r.id) + '">Use this structure</button></div></article>';
    }).join("") : '<p class="empty">No approved slides match. Try a business question such as “why did costs rise”.</p>';
  }
  $("#repoFilters").addEventListener("click", function (e) { var b = e.target.closest("button"); if (!b) return; repoCat = b.textContent; renderRepo(); });
  $("#repoSearch").addEventListener("input", renderRepo);
  $("#repoGrid").addEventListener("click", function (e) {
    var b = e.target.closest("[data-id]"); if (!b) return;
    var r = repo.filter(function (x) { return x.id === b.dataset.id; })[0];
    addSlide({ kind: r.kind, headline: r.headline || (r.title + ": [state your finding]"), body: (r.structure || []).slice(), visual: LAYOUT[r.kind], notes: "", evidence: { status: "needed", gap: "Add supporting data", source: "" } }, r.title);
  });

  /* ------------------------------------------------------------------ boot */
  (async function boot() {
    renderPipeline();
    try { await loadMeta(); }
    catch (e) { toast("Cannot reach the studio server: " + e.message, true); }
    var restored = restore();
    if (!restored) $("#topic").value = "";
    $("#dropzone").hidden = radio("src") === "scratch" && state.files.length === 0;
    $("#lenField").hidden = radio("task") === "single";
    renderFiles();
    renderPipeline();
    renderDeck();
    renderXform();
    loadHealth();
    var v = null; try { v = localStorage.getItem("eps-view"); } catch (e) { v = null; }
    if (v && $("#view-" + v)) show(v);
  })();
})();
