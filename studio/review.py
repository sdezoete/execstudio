"""Deterministic executive-readiness checks. Fast, explainable and identical every run."""
import re

from .catalog import AUDIENCE_BY_ID, slide_range, template
from .checks import MAX_HEADLINE_WORDS, TOPIC_LABEL as _TOPIC_LABEL

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
            (_PLACEHOLDER.search(s["headline"]) or _TOPIC_LABEL.search(s["headline"]) or _words(s["headline"]) < 5)]
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


# Additive units only: points and amounts. Percent growth rates are not additive (segments at +12% and
# -3% can make +4% overall), so "%" is deliberately absent.
_QTY = re.compile(r"([+\-−]?\d+(?:\.\d+)?)\s*(pts|pp|ppt|m|bn|k)\b", re.I)
_PHANTOM = re.compile(r"\b(unexplained|not specified|unspecified|unaccounted|remaining (gap|decline|difference)|other factors)\b", re.I)


def _sum_problem(slide):
    """The headline's figure is the total; body figures in the same unit are its parts. Flags parts that
    overshoot the total, and a "remaining gap" that cannot exist because the parts already make the total
    (test report D-06: freight 0.9 + materials 1.2 = 2.1 pts, yet the slide called part of it unspecified)."""
    head = _QTY.findall(slide["headline"])
    if not head:
        return ""
    total_s, unit = max(head, key=lambda q: abs(float(q[0].replace("−", "-"))))
    total, unit = abs(float(total_s.replace("−", "-"))), unit.lower()
    parts = [abs(float(n.replace("−", "-"))) for b in slide["body"] for n, u in _QTY.findall(b) if u.lower() == unit]
    if len(parts) < 2:
        return ""
    s = round(sum(parts), 4)
    shown = " + ".join("%g" % p for p in parts) + " = %g %s" % (s, unit)
    if s > total + 0.051:
        return "the parts (%s) are more than the total of %g %s" % (shown, total, unit)
    text = " ".join([slide["headline"]] + slide["body"] + [slide.get("notes") or ""])
    if abs(s - total) <= 0.051 and _PHANTOM.search(text):
        return "the parts already make the total (%s), but the slide says part of it is unexplained" % shown
    return ""


def _list(nums):
    nums = [str(n) for n in nums]
    if len(nums) == 1:
        return nums[0]
    return ", ".join(nums[:-1]) + " and " + nums[-1]
