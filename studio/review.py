"""Deterministic executive-readiness checks. Fast, explainable and identical every run."""
import re

from .catalog import AUDIENCE_BY_ID, slide_range, template

_PLACEHOLDER = re.compile(r"\[[^\]]+\]")
_TOPIC_LABEL = re.compile(r"^(overview|update|summary|introduction|agenda|review|background)\b", re.I)


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

    long_h = [i + 1 for i, s in enumerate(slides) if _words(s["headline"]) > 15]
    checks.append({
        "ok": not long_h,
        "title": "Headlines are concise",
        "detail": "All headlines are 15 words or fewer." if not long_h else
        "Shorten the headline on slide%s %s to 15 words or fewer." % ("s" if len(long_h) > 1 else "", _list(long_h)),
    })

    missing = [(i + 1, s["evidence"].get("gap") or "Evidence needed") for i, s in enumerate(slides)
               if s["evidence"]["status"] != "linked"]
    checks.append({
        "ok": not missing,
        "title": "Claims are backed by evidence",
        "detail": "Every slide links to a source." if not missing else
        "; ".join("Slide %d: %s" % m for m in missing[:6]) + ("…" if len(missing) > 6 else ""),
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
    too_long = brief["audience"] == "board" and n > 10
    checks.append({
        "ok": not too_long,
        "title": "Length fits the audience",
        "detail": ("Board decks work best at 10 slides or fewer. Move detail to the appendix."
                   if too_long else "%d slide%s suits %s." % (n, "" if n == 1 else "s", aud["label"].lower())),
    })

    t = template(brief["template"])
    checks.append({"ok": True, "title": "Approved template applied", "detail": t["name"] + " masters, fonts and colours."})
    return {"checks": checks, "range": [lo, hi]}


def _list(nums):
    nums = [str(n) for n in nums]
    if len(nums) == 1:
        return nums[0]
    return ", ".join(nums[:-1]) + " and " + nums[-1]
