/* Slide layout thumbnails, drawn as inline SVG so nothing loads from outside the server. */
(function () {
  "use strict";

  var LAYOUT = {
    title: "Title", summary: "Answer-first summary", kpi: "KPI scorecard", bars: "Variance chart",
    driver: "Driver tree", matrix: "Options matrix", decision: "Decision brief", roadmap: "Roadmap",
    risk: "Risk heat map", table: "Data table"
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* A simple, content-populated stand-in for the slide: real headline and bullets,
     laid out the same way for every kind. Not a layout-accurate render of the final
     PowerPoint (that stays in python-pptx/layouts.py) -- just enough to read the slide
     at a glance instead of an abstract icon. No new dependencies, nothing server-side. */
  function preview(s) {
    s = s || {};
    var body = (s.body || []).slice(0, 4);
    var visual = s.visual || LAYOUT[s.kind] || "";
    return '<div class="slide-preview" role="img" aria-label="Slide preview">' +
      '<div class="pv-acc"></div>' +
      '<div class="pv-body">' +
        '<div class="pv-head">' + esc(s.headline) + "</div>" +
        (body.length ? '<ul class="pv-list">' + body.map(function (b) { return "<li>" + esc(b) + "</li>"; }).join("") + "</ul>" : "") +
        (visual ? '<div class="pv-visual">' + esc(visual) + "</div>" : "") +
      "</div></div>";
  }

  function svg(kind) {
    var head = '<rect class="s-ink" x="10" y="9" width="104" height="6" rx="1"/><rect class="s-mute" x="10" y="18" width="62" height="3" rx="1"/>';
    var foot = '<rect class="s-mute" x="10" y="82" width="28" height="2.4" rx="1"/><rect class="s-mute" x="136" y="82" width="14" height="2.4" rx="1"/>';
    var b = "", i, x, y, r, c;
    switch (kind) {
      case "title":
        return wrap('<rect class="s-acc" x="10" y="26" width="20" height="3"/><rect class="s-ink" x="10" y="36" width="112" height="9" rx="1"/><rect class="s-mute" x="10" y="50" width="70" height="4" rx="1"/>' + foot);
      case "summary":
        [32, 47, 62].forEach(function (y) {
          b += '<rect class="s-acc" x="10" y="' + y + '" width="4" height="9"/><rect class="s-ink" x="19" y="' + y + '" width="104" height="4" rx="1"/><rect class="s-mute" x="19" y="' + (y + 6) + '" width="80" height="3" rx="1"/>';
        });
        break;
      case "kpi":
        for (i = 0; i < 4; i++) {
          x = 10 + i * 36;
          b += '<rect class="s-tile" x="' + x + '" y="30" width="32" height="40" rx="2"/><rect class="s-ink" x="' + (x + 4) + '" y="38" width="18" height="8" rx="1"/><rect class="s-mute" x="' + (x + 4) + '" y="51" width="22" height="3" rx="1"/><rect class="' + (i % 2 ? "s-warn" : "s-acc") + '" x="' + (x + 4) + '" y="60" width="10" height="3" rx="1"/>';
        }
        break;
      case "bars":
        b = '<rect class="s-mute" x="10" y="72" width="140" height="0.8"/>';
        [22, 30, 26, 36, 40, 34, 44].forEach(function (h, i) {
          b += '<rect class="' + (i >= 5 ? "s-acc" : "s-mute") + '" x="' + (16 + i * 19) + '" y="' + (72 - h) + '" width="12" height="' + h + '"/>';
        });
        break;
      case "driver":
        b = '<path class="s-line" d="M38 52 H50 M50 36 V68 M50 36 H60 M50 52 H60 M50 68 H60 M92 36 H104 M92 68 H104"/><rect class="s-acc" x="10" y="46" width="28" height="12" rx="1.5"/>';
        [30, 46, 62].forEach(function (y, i) { b += '<rect class="' + (i === 0 ? "s-warn" : "s-tile") + '" x="60" y="' + y + '" width="32" height="12" rx="1.5"/>'; });
        [30, 62].forEach(function (y) { b += '<rect class="s-tile" x="104" y="' + y + '" width="40" height="12" rx="1.5"/>'; });
        break;
      case "matrix":
        b = '<rect class="s-mute" x="38" y="28" width="0.8" height="50"/><rect class="s-mute" x="38" y="77" width="96" height="0.8"/>';
        [[40, 29], [87, 29], [40, 53], [87, 53]].forEach(function (p, i) {
          b += '<rect class="' + (i === 1 ? "s-acc" : "s-tile") + '" x="' + p[0] + '" y="' + p[1] + '" width="45" height="22" rx="1.5"/>';
        });
        b += '<rect class="s-mute" x="10" y="40" width="22" height="3"/><rect class="s-mute" x="10" y="62" width="22" height="3"/>';
        break;
      case "decision":
        b = '<rect class="s-tile" x="10" y="29" width="140" height="36" rx="2"/><rect class="s-acc" x="10" y="29" width="3" height="36"/><rect class="s-ink" x="20" y="36" width="96" height="6" rx="1"/><rect class="s-mute" x="20" y="47" width="110" height="3" rx="1"/><rect class="s-mute" x="20" y="54" width="84" height="3" rx="1"/><rect class="s-acc" x="10" y="70" width="34" height="6" rx="1"/>';
        break;
      case "roadmap":
        b = '<rect class="s-mute" x="10" y="54" width="140" height="0.8"/>';
        [["s-acc", 10, 40], ["s-ink", 54, 46], ["s-mute", 104, 46]].forEach(function (p, i) {
          b += '<rect class="' + p[0] + '" x="' + p[1] + '" y="' + (36 + i * 5) + '" width="' + (p[2] - 4) + '" height="5" rx="1"/>';
        });
        [40, 90, 140].forEach(function (x) { b += '<rect class="s-acc" x="' + (x - 3) + '" y="51" width="6" height="6" transform="rotate(45 ' + x + ' 54)"/>'; });
        b += '<rect class="s-mute" x="10" y="64" width="34" height="3"/><rect class="s-mute" x="54" y="64" width="34" height="3"/><rect class="s-mute" x="104" y="64" width="34" height="3"/>';
        break;
      case "risk":
        for (r = 0; r < 3; r++) for (c = 0; c < 3; c++) {
          var lvl = r + c;
          b += '<rect class="' + (lvl >= 3 ? "s-warn" : lvl === 2 ? "s-mute" : "s-tile") + '" x="' + (10 + c * 17) + '" y="' + (29 + r * 15) + '" width="15" height="13" rx="1"/>';
        }
        [32, 44, 56, 68].forEach(function (y) { b += '<rect class="s-ink" x="72" y="' + y + '" width="60" height="3.5" rx="1"/><rect class="s-mute" x="72" y="' + (y + 5) + '" width="44" height="2.5"/>'; });
        break;
      default: /* table */
        for (i = 0; i < 6; i++) b += '<rect class="' + (i === 0 ? "s-ink" : "s-tile") + '" x="10" y="' + (29 + i * 8) + '" width="140" height="6"/>';
    }
    return wrap(head + b + foot);

    function wrap(inner) {
      return '<svg class="mini" viewBox="0 0 160 90" role="img" aria-label="' + (LAYOUT[kind] || "Slide") + ' layout"><rect class="s-bg" width="160" height="90" rx="3"/>' + inner + "</svg>";
    }
  }

  window.Thumbs = { svg: svg, preview: preview, LAYOUT: LAYOUT };
})();
