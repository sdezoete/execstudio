"""Deterministic executive-readiness checks. Fast, explainable and identical every run."""
import re

from .catalog import AUDIENCE_BY_ID, slide_range, template
from .checks import MAX_HEADLINE_WORDS, MIN_HEADLINE_WORDS, TOPIC_LABEL as _TOPIC_LABEL

_PLACEHOLDER = re.compile(r"\[[^\]]+\]")


def _words(s):
    return len(s.split())


def run(brief, slides):
    checks = []
    content = [s for s in slides if s["kind"] != "title"]

    lead = content[0]["kind"] if content else None
    checks.append({
        "ok": lead in ("summary", "decision"),
        "title": "Leads with the answer",
        "detail": "The first content slide states the conclusion." if lead in ("summary", "decision")
        else "Move an answer-first summary or the decision to the start of the deck.",
    })

    weak = [i + 1 for i, s in enumerate(slides) if s["kind"] != "title" and
            (_PLACEHOLDER.search(s["headline"]) or _TOPIC_LABEL.search(s["headline"]) or _words(s["headline"]) < MIN_HEADLINE_WORDS)]
    checks.append({
        "ok": not weak,
        "title": "Every slide has an action title",
        "detail": "Headlines state a finding, not a topic." if not weak else
        "Slide%s %s still need%s a headline that states the finding." % ("s" if len(weak) > 1 else "", _list(weak), "" if len(weak) > 1 else "s"),
    })

    long_h = [i + 1 for i, s in enumerate(slides) if _words(s["headline"]) > MAX_HEADLINE_WORDS]
    checks.append({
        "ok": not long_h,
        "title": "Headlines are concise",
        "detail": "All headlines are %d words or fewer." % MAX_HEADLINE_WORDS if not long_h else
        "Shorten the headline on slide%s %s to %d words or fewer." % ("s" if len(long_h) > 1 else "", _list(long_h), MAX_HEADLINE_WORDS),
    })

    missing = [(i + 1, s["evidence"].get("gap") or "Evidence needed") for i, s in enumerate(slides)
               if s["evidence"]["status"] != "linked"]
    checks.append({
        "ok": not missing,
        "title": "Claims are backed by evidence",
        "detail": "Every slide links to a source." if not missing else
        "; ".join("Slide %d: %s" % m for m in missing[:6]) + ("…" if len(missing) > 6 else ""),
    })

    sums = [(i + 1, p) for i, s in enumerate(slides) for p in [_sum_problem(s)] if p]
    checks.append({
        "ok": not sums,
        "title": "Figures add up",
        "detail": "Parts and totals reconcile." if not sums else
        "; ".join("Slide %d: %s" % m for m in sums[:4]),
    })

    dense = [i + 1 for i, s in enumerate(slides) if len(s["body"]) > 5 or any(_words(b) > 25 for b in s["body"])]
    checks.append({
        "ok": not dense,
        "title": "One message per slide",
        "detail": "Slides are focused and readable." if not dense else
        "Slide%s %s carr%s too much text. Keep to five points of 25 words or fewer." % ("s" if len(dense) > 1 else "", _list(dense), "y" if len(dense) > 1 else "ies"),
    })

    has_decision_text = bool(brief["decision"])
    has_decision_slide = any(s["kind"] == "decision" for s in slides)
    ok = has_decision_text and has_decision_slide
    checks.append({
        "ok": ok,
        "title": "Decision is explicit",
        "detail": "The ask has its own slide." if ok else
        ("Add the decision you need to the brief so leaders know what to approve." if not has_decision_text
         else "Add a decision slide that states the ask."),
    })

    aud = AUDIENCE_BY_ID[brief["audience"]]
    lo, hi = slide_range(brief["length"], "full", brief["task"])
    n = len(slides)
    too_long = brief["audience"] == "executive" and n > 10
    checks.append({
        "ok": not too_long,
        "title": "Length fits the audience",
        "detail": ("Executive decks work best at 10 slides or fewer. Move detail to the appendix."
                   if too_long else "%d slide%s suits %s." % (n, "" if n == 1 else "s", aud["label"].lower())),
    })

    t = template(brief["template"])
    checks.append({"ok": True, "title": "Approved template applied", "detail": t["name"] + " masters, fonts and colours."})
    return {"checks": checks, "range": [lo, hi]}


# "Figures add up" works on additive quantities: points and amounts, plus shares of a whole. Percent
# growth rates are not additive (segments at +12% and -3% can make +4% overall), and actual / plan /
# variance figures are not parts of a total (N-02: "48.2m vs plan 51.0m, a 2.8m miss" is not
# 48.2 + 51 + 2.8), so both are left alone.
_N = r"[+\-−]?\d[\d,]*(?:\.\d+)?"
_UNIT = r"(pts?|points?|percentage points?|pp|ppt|m|mn|million|bn|billion|k|thousand|%)"
_QTY = re.compile(r"(" + _N + r")\s*-?\s*" + _UNIT + r"(?![A-Za-z])", re.I)
_UNITS = {"pt": "pts", "pts": "pts", "point": "pts", "points": "pts", "percentage point": "pts", "percentage points": "pts",
          "pp": "pts", "ppt": "pts", "m": "m", "mn": "m", "million": "m", "bn": "bn", "billion": "bn",
          "k": "k", "thousand": "k", "%": "%"}
_EQUATION = re.compile(r"(" + _N + r")(?:\s*-?\s*" + _UNIT + r")?((?:\s*(?:\+|plus)\s*" + _N + r"(?:\s*-?\s*" + _UNIT + r")?)+)"
                       r"\s*(?:=|equals?|makes?|gives?|sums? to|adds? up to|totals?|come to|comes to)\s*(?:the\s+|a\s+)?(" + _N + r")", re.I)
_TOTAL = re.compile(r"\b(total|overall|in all|altogether|combined)\b", re.I)
_PHANTOM = re.compile(r"\b(unexplained|not specified|unspecified|unaccounted|remaining (gap|decline|difference)|other factors)\b", re.I)
_PARTIAL = re.compile(r"\b(other|others|rest|remainder|remaining|mainly|largely|main|primarily|partly|partially|including|such as)\b", re.I)
_COMPARISON = re.compile(r"\b(vs\.?|versus|against|plan|target|budget|forecast|prior year|last year|actual)\b", re.I)
_SHARE = re.compile(r"\b(share|shares|mix|split|breakdown|portion|composition|of (total|revenue|sales|spend|volume|the total))\b", re.I)
_GROWTH = re.compile(r"[+\-−]\s*\d|\b(up|down|growth|grew|rose|fell|increase\w*|decrease\w*|decline\w*|yoy|qoq)\b", re.I)


def _num(s):
    return abs(float(s.replace("−", "-").replace(",", "")))


def _qty(text, unit=None):
    """[(value, unit)] in text, units normalised; only `unit` if given."""
    out = [(_num(n), _UNITS[u.lower()]) for n, u in _QTY.findall(text or "")]
    return [q for q in out if unit is None or q[1] == unit]


def _close(a, b):
    return abs(a - b) <= max(0.051, 0.005 * max(a, b))  # rounding to one decimal, or 0.5%


def _sum_problem(slide):
    """Parts that do not make their total. Three cases:
    - a written sum that is wrong ("0.9 plus 1.6 equals the 2.1-point decline");
    - parts against a total that is labelled ("Total EUR 48.2m"), or on a driver slide the headline's
      figure: parts above the total, parts below it with nothing said about the rest, or a "remaining
      gap" that cannot exist because the parts already make the total (D-06);
    - shares of a whole that add up to more than 100%."""
    lines = [slide["headline"]] + list(slide["body"])
    text = " ".join(lines + [slide.get("notes") or ""])

    for line in lines:
        m = _EQUATION.search(line)
        if m:
            left = [_num(m.group(1))] + [_num(n) for n in re.findall(_N, m.group(3))]
            right = _num(m.group(5))
            if not _close(sum(left), right):
                return "%s makes %g, not %g" % (" + ".join("%g" % x for x in left), sum(left), right)

    total = None
    for line in lines:
        if _TOTAL.search(line) and not _COMPARISON.search(line):
            q = [x for x in _qty(line) if x[1] != "%"]
            if q:
                total, total_line = max(q), line
                break
    if total is None and slide.get("kind") == "driver":
        q = [x for x in _qty(slide["headline"]) if x[1] != "%"]
        if q:
            total, total_line = max(q), slide["headline"]
    if total is not None:
        value, unit = total
        # a line carrying the total's own value restates it ("together they explain the full 2.1-point
        # decline"); it is not one more part
        parts = [v for b in slide["body"] if b != total_line and not _COMPARISON.search(b) and not _EQUATION.search(b)
                 and not _TOTAL.search(b) and not any(_close(x, value) for x, _u in _qty(b, unit))
                 for v, _u in _qty(b, unit)]
        if len(parts) >= 2:
            s = round(sum(parts), 4)
            shown = " + ".join("%g" % p for p in parts) + " = %g %s" % (s, unit)
            if s > value and not _close(s, value):
                return "the parts (%s) are more than the total of %g %s" % (shown, value, unit)
            if _close(s, value) and _PHANTOM.search(text):
                return "the parts already make the total (%s), but the slide says part of it is unexplained" % shown
            if s < value and not _close(s, value) and not _PARTIAL.search(text):
                return "the parts (%s) fall short of the total of %g %s; name the rest or correct a figure" % (shown, value, unit)

    if _SHARE.search(text):
        shares = [v for b in slide["body"] if not _COMPARISON.search(b) and not _GROWTH.search(b) for v, _u in _qty(b, "%")]
        if len(shares) >= 2 and sum(shares) > 100.5:
            return "the shares (%s) add up to %g%%, more than 100%%" % (" + ".join("%g%%" % x for x in shares), sum(shares))
    return ""


def _list(nums):
    nums = [str(n) for n in nums]
    if len(nums) == 1:
        return nums[0]
    return ", ".join(nums[:-1]) + " and " + nums[-1]
