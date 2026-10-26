"""Slide layouts, written once against a small drawing "canvas".

Both PowerPoint engines implement the same canvas:
  - pptx_engine.PptxCanvas  (python-pptx, corporate template, native charts)
  - xml_engine.XmlCanvas    (standard library fallback)

Canvas API (all measurements in inches):
  c.colors                   dict: accent, ink, muted, tile, warn, white
  c.box(x, y, w, h, fill, line=None, geom="rect")
  c.text(x, y, w, h, lines, size=16, bold=False, color=None, align="l",
         bullet=False, fill=None, line=None, geom="rect", anchor="t", inset=0.08)
  c.chart(x, y, w, h, spec) -> bool   (False when the engine can't draw charts)

`area` is the content region (x, y, w, h) below the headline.
"""
import re

from ..checks import is_placeholder
from .rtl import is_rtl


# Labels the layouts draw themselves, in Arabic for a slide written in Arabic (round 6: English labels on
# Arabic slides). Arrows point the way an Arabic reader reads the axis.
_ARABIC = {
    "[Add content]": "[أضف المحتوى]", "Source: ": "المصدر: ", "Evidence gap: ": "أدلة مطلوبة: ",
    "Moved from the slide:": "نُقل من الشريحة:", "Phase %d": "المرحلة %d", "DECISION REQUIRED": "القرار المطلوب",
    "Value": "القيمة", "Risk and effort →": "← المخاطر والجهد", "Likelihood": "الاحتمال", "Impact →": "← الأثر",
    "Small print on the original slide:": "نص صغير في الشريحة الأصلية:",
}


def label(slide, text):
    """`text` as the slide's reader expects it: Arabic when the slide's own text is right-to-left."""
    words = " ".join([slide.get("headline") or ""] + list(slide.get("body") or []))
    return _ARABIC.get(text, text) if is_rtl(words) else text


def items(slide, n, default="[Add content]"):
    """The first n body points. Points that do not fit the layout are recorded on the slide as
    "overflow"; the engines put them in the speaker notes, so nothing is silently lost."""
    body = list(slide.get("body") or [])
    if len(body) > n:
        slide["overflow"] = body[n:]
    return body[:n] if body else [label(slide, default)]


def notes_text(slide):
    """Speaker notes plus any points moved off the slide by items()."""
    notes = (slide.get("notes") or "").strip()
    if slide.get("overflow"):
        notes = (notes + "\n\n" + label(slide, "Moved from the slide:") + "\n" +"\n".join("- " + x for x in slide["overflow"])).strip()
    return notes


def evidence_note(slide):
    """The footer line for a slide's evidence: ("Source: …", False), ("Evidence gap: …", True) for a gap
    that actually says something, or ("", False). A bare "Evidence needed" default is not repeated."""
    ev =slide.get("evidence") or {}
    if ev.get("status") == "linked":
        return (label(slide, "Source: ") + ev["source"], False) if ev.get("source") else ("", False)
    gap = (ev.get("gap") or "").strip()
    return (label(slide, "Evidence gap: ") + gap, True) if gap and not is_placeholder(gap) else ("", False)


def valid_chart(spec):
    """True when a chart spec has categories and at least one numeric series of matching length."""
    if not isinstance(spec, dict):
        return False
    cats = spec.get("categories") or []
    series = spec.get("series") or []
    if not cats or not series:
        return False
    for s in series:
        vals = s.get("values") if isinstance(s, dict) else None
        if not isinstance(vals, list) or len(vals) != len(cats):
            return False
        if not all(isinstance(v, (int, float)) for v in vals):
            return False
    return True


# ------------------------------------------------------------------ layouts
def lay_summary(c, s, area):
    ax, ay, aw, ah = area
    its = items(s, 5)
    row = min(1.15, ah / len(its))
    for i, it in enumerate(its):
        y = ay + i * row
        c.text(ax, y + 0.08, 0.5, 0.5, str(i + 1), size=16, bold=True, color=c.colors["white"], align="ctr",
               fill=c.colors["accent"], anchor="ctr", inset=0.02)
        c.text(ax + 0.75, y, aw - 0.75, row - 0.1, it, size=18, anchor="ctr")


def lay_kpi(c, s, area):
    ax, ay, aw, ah = area
    its = items(s, 6)
    per_row = 3 if len(its) > 4 else len(its)
    rows = (len(its) + per_row - 1) // per_row
    gap = 0.25
    w = (aw - gap * (per_row - 1)) / per_row
    h = (ah - 0.2 - gap * (rows - 1)) / rows
    for i, it in enumerate(its):
        r, col = divmod(i, per_row)
        x, y = ax + col * (w + gap), ay + r * (h + gap)
        c.box(x, y, w, h, fill=c.colors["tile"])
        c.box(x, y, w, 0.07, fill=c.colors["accent"])
        c.text(x + 0.15, y + 0.25, w - 0.3, h - 0.4, it, size=18, anchor="ctr")


def lay_bars(c, s, area):
    ax, ay, aw, ah = area
    cw = aw * 0.62
    drawn = valid_chart(s.get("chart")) and c.chart(ax, ay, cw, ah - 0.1, s["chart"])
    if not drawn:
        c.text(ax, ay, cw, ah - 0.1,
               ["Chart: " + (s.get("visual") or "insert chart"), "Insert the chart from your approved data source"],
               size=14, bold=False, color=c.colors["muted"], align="ctr", fill=c.colors["tile"], anchor="ctr")
    c.text(ax + cw + 0.35, ay, aw - cw - 0.35, ah - 0.1, items(s, 5), size=16, bullet=True)


def lay_driver(c, s, area):
    ax, ay, aw, ah = area
    its = items(s, 4)
    root_w, root_h = 2.8, 1.3
    ry = ay + (ah - root_h) / 2
    c.text(ax, ry, root_w, root_h, s.get("visual") or "Outcome", size=16, bold=True, color=c.colors["white"],
           align="ctr", fill=c.colors["accent"], anchor="ctr")
    n, gap = len(its), 0.2
    bh = min(1.05, (ah - gap * (n - 1)) / n)
    total = n * bh + (n - 1) * gap
    top = ay + (ah - total) / 2
    spine = ax + root_w + 0.45
    bx = spine + 0.45
    c.box(ax + root_w, ry + root_h / 2 - 0.015, 0.45, 0.03, fill=c.colors["muted"])
    if n > 1:
        c.box(spine - 0.015, top + bh / 2, 0.03, total - bh, fill=c.colors["muted"])
    for i, it in enumerate(its):
        y = top + i * (bh + gap)
        c.box(spine, y + bh / 2 - 0.015, 0.45, 0.03, fill=c.colors["muted"])
        c.text(bx, y, ax + aw - bx, bh, it, size=16, fill=c.colors["tile"] if i else None,
               line=None if i else c.colors["warn"], anchor="ctr", inset=0.12)


def lay_matrix(c, s, area):
    ax, ay, aw, ah = area
    its = items(s, 4)
    rec = next((i for i, t in enumerate(its) if re.search(r"recommend", t, re.I)), 0)
    gx, gw, gh = ax + 0.9, aw - 0.9, ah - 0.45
    qw, qh = (gw - 0.15) / 2, (gh - 0.15) / 2
    for i, (col, r) in enumerate([(0, 0), (1, 0), (0, 1), (1, 1)]):
        x, y = gx + col * (qw + 0.15), ay + r * (qh + 0.15)
        cell = its[i] if i < len(its) else ""
        hi = bool(cell) and i == rec
        c.text(x, y, qw, qh, cell, size=16, bold=hi, color=c.colors["white"] if hi else c.colors["ink"],
               fill=c.colors["accent"] if hi else c.colors["tile"], anchor="ctr", inset=0.15)
    c.text(ax, ay, 0.85, gh, [label(s, "Value"), "↑"], size=11, color=c.colors["muted"], align="ctr", anchor="ctr")
    c.text(gx, ay + gh + 0.05, gw, 0.35, label(s, "Risk and effort →"), size=11, color=c.colors["muted"], align="ctr")


def lay_decision(c, s, area):
    ax, ay, aw, ah = area
    c.box(ax, ay, aw, ah - 0.15, fill=c.colors["tile"])
    c.box(ax, ay, 0.09, ah - 0.15, fill=c.colors["accent"])
    c.text(ax + 0.4, ay + 0.25, 8, 0.4, label(s, "DECISION REQUIRED"), size=12, bold=True, color=c.colors["accent"])
    c.text(ax + 0.4, ay + 0.75, aw - 0.8, ah - 1.1, items(s, 5), size=18, bullet=True)


def lay_roadmap(c, s, area):
    ax, ay, aw, ah = area
    its = items(s, 5)
    w = aw / len(its)
    fills = [c.colors["accent"], c.colors["ink"], c.colors["muted"], c.colors["accent"], c.colors["ink"]]
    for i, it in enumerate(its):
        x = ax + i * w
        head, _, rest = it.partition(":")
        c.text(x, ay + 0.2, w + 0.12, 0.9, head.strip() if rest else label(s, "Phase %d") % (i + 1), size=16, bold=True,
               color=c.colors["white"], align="ctr", fill=fills[i], geom="homePlate" if i == 0 else "chevron", anchor="ctr")
        c.text(x + 0.1, ay + 1.35, w - 0.25, ah - 1.5, (rest or it).strip(), size=15)


def lay_risk(c, s, area):
    ax, ay, aw, ah = area
    cell = min(0.95, (ah - 0.6) / 3)
    gx, gy = ax + 1.0, ay + 0.2
    for r in range(3):
        for col in range(3):
            lvl = (2 - r) + col
            fill = c.colors["warn"] if lvl >= 3 else c.colors["muted"] if lvl == 2 else c.colors["tile"]
            c.box(gx + col * (cell + 0.08), gy + r * (cell + 0.08), cell, cell, fill=fill)
    c.text(ax, gy, 0.95, 3 * cell + 0.16, [label(s, "Likelihood"), "↑"], size=10, color=c.colors["muted"], align="ctr", anchor="ctr")
    c.text(gx, gy + 3 * (cell + 0.08), 3 * cell + 0.16, 0.35, label(s, "Impact →"), size=10, color=c.colors["muted"], align="ctr")
    lx = gx + 3 * (cell + 0.08) + 0.6
    c.text(lx, ay, ax + aw - lx, ah - 0.1, items(s, 5), size=16, bullet=True)


def lay_table(c, s, area):
    ax, ay, aw, ah = area
    its = items(s, 8)
    rh = min(0.6, (ah - 0.1) / len(its))
    for i, it in enumerate(its):
        c.text(ax, ay + i * rh, aw, rh - 0.04, it, size=15, fill=c.colors["tile"] if i % 2 == 0 else None,
               anchor="ctr", inset=0.12)


def lay_bullets(c, s, area):
    ax, ay, aw, ah = area
    c.text(ax, ay, aw, ah, items(s, 8), size=18, bullet=True)


LAYOUTS = {"summary": lay_summary, "kpi": lay_kpi, "bars": lay_bars, "driver": lay_driver, "matrix": lay_matrix,
           "decision": lay_decision, "roadmap": lay_roadmap, "risk": lay_risk, "table": lay_table}


def draw(c, slide, area):
    """Draw the body of any non-title slide; a slide with chart data always gets its chart."""
    kind = slide["kind"]
    if kind != "bars" and valid_chart(slide.get("chart")):
        kind = "bars"
    LAYOUTS.get(kind, lay_summary)(c, slide, area)
