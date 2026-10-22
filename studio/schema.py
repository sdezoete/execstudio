"""Validation and normalisation of data coming from the browser or the LLM."""
from .catalog import (AUDIENCE_BY_ID, BOARD_EXTERNAL_ONLY, BOARD_READINESS_DIMENSIONS, BOARD_RULES,
                       KINDS, LENGTHS, PRESENTATION_TYPES, STAGE_GATES)

TASKS = ("new", "improve", "single", "find")
SOURCES = ("scratch", "docs", "deck")
VERSIONS = ("full", "summary", "brief")


class BadRequest(Exception):
    pass


def _s(v, limit):
    if v is None:
        return ""
    if not isinstance(v, str):
        v = str(v)
    return v.strip()[:limit]


def brief(raw):
    if not isinstance(raw, dict):
        raise BadRequest("The brief is missing.")
    b = {
        "task": raw.get("task") if raw.get("task") in TASKS else "new",
        "topic": _s(raw.get("topic"), 300),
        "decision": _s(raw.get("decision"), 400),
        "facts": _s(raw.get("facts"), 8000),
        "audience": raw.get("audience") if raw.get("audience") in AUDIENCE_BY_ID else "executive",
        "length": raw.get("length") if raw.get("length") in LENGTHS else "mid",
        "source": raw.get("source") if raw.get("source") in SOURCES else "scratch",
        "template": _s(raw.get("template"), 60),
        "template_file": _s(raw.get("template_file"), 40),  # workspace id of an ad-hoc uploaded template, if any
    }
    return b


def slide(raw):
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    if kind not in KINDS:
        kind = "summary"
    body = raw.get("body") or []
    if isinstance(body, str):
        body = [x for x in body.split("\n")]
    body = [_s(x, 300) for x in body if _s(x, 300)][:8]
    ev = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
    status = "linked" if ev.get("status") == "linked" else "needed"
    headline = _s(raw.get("headline") or raw.get("title"), 300)
    if not headline:
        return None
    out = {
        "kind": kind,
        "headline": headline,
        "body": body,
        "visual": _s(raw.get("visual"), 120),
        "notes": _s(raw.get("notes"), 2000),
        "evidence": {"status": status, "source": _s(ev.get("source"), 200),
                     "gap": "" if status == "linked" else (_s(ev.get("gap"), 120) or "Evidence needed")},
    }
    ch = chart(raw.get("chart"))
    if ch:
        out["chart"] = ch
    return out


CHART_TYPES = ("column", "bar", "line", "stacked")


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        t = v.strip().replace(",", "").replace("%", "").replace("$", "")
        try:
            return float(t)
        except ValueError:
            return None
    return None


def chart(raw):
    """Normalise a chart spec; returns None unless it has categories and fully numeric, matching series."""
    if not isinstance(raw, dict):
        return None
    cats = [_s(c, 40) for c in (raw.get("categories") or [])][:24]
    series = []
    for s in (raw.get("series") or [])[:6]:
        if not isinstance(s, dict):
            return None
        vals = [_num(v) for v in (s.get("values") or [])]
        if len(vals) != len(cats) or any(v is None for v in vals):
            return None
        series.append({"name": _s(s.get("name"), 60) or "Series", "values": vals})
    if not cats or not series:
        return None
    return {"type": raw.get("type") if raw.get("type") in CHART_TYPES else "column",
            "title": _s(raw.get("title"), 120), "categories": cats, "series": series}


def slides(raw, max_slides=30):
    if not isinstance(raw, list):
        raise BadRequest("The slide list is missing.")
    out = [s for s in (slide(x) for x in raw[:max_slides]) if s]
    return out


def storyline(raw, fallback_title):
    """Normalise an LLM storyline; raises ValueError if unusable."""
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    sl = slides(raw.get("slides") or [])
    if not sl:
        raise ValueError("no slides")
    return {"title": _s(raw.get("title"), 200) or fallback_title, "slides": sl}


# --------------------------------------------------------------- GEC/GIC board assessment
BOARD_RESULTS = ("PASS", "FAIL", "WARNING", "NOT VERIFIABLE", "NOT APPLICABLE")


def board_context(raw):
    if not isinstance(raw, dict):
        raw = {}
    return {
        "presentation_type": raw.get("presentation_type") if raw.get("presentation_type") in PRESENTATION_TYPES else "",
        "stage_gate": raw.get("stage_gate") if raw.get("stage_gate") in STAGE_GATES else "",
        "ook_investment": raw.get("ook_investment") if raw.get("ook_investment") in ("yes", "no") else "",
        "submission_date": _s(raw.get("submission_date"), 10),
        "meeting_date": _s(raw.get("meeting_date"), 10),
    }


def board_result(raw):
    """Normalise the LLM's board-assessment JSON into the canonical shape. Fields that are
    missing or malformed become a safe default (NOT VERIFIABLE / unscored); raises ValueError
    only if the model engaged with neither section at all, so the caller falls back to rules."""
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    by_id = {str(it.get("id")): it for it in (raw.get("compliance") or []) if isinstance(it, dict) and it.get("id")}
    if not by_id and not isinstance(raw.get("board_readiness"), dict):
        raise ValueError("empty board assessment")
    compliance = []
    for rule in BOARD_RULES:
        if rule["id"] == "SUB-01":
            continue  # computed separately in services.py, from the supplied dates
        it = by_id.get(rule["id"], {})
        result = it.get("result") if it.get("result") in BOARD_RESULTS else "NOT VERIFIABLE"
        if rule["id"] in BOARD_EXTERNAL_ONLY and result in ("PASS", "FAIL"):
            result = "NOT VERIFIABLE"  # no evidence pipeline exists for sign-offs/consultations/templates
        compliance.append({
            "id": rule["id"], "category": rule["category"], "requirement": rule["requirement"],
            "critical": bool(rule.get("critical")), "result": result,
            "evidence": _s(it.get("evidence"), 500), "action": _s(it.get("action"), 400),
        })

    raw_scores = raw.get("board_readiness") if isinstance(raw.get("board_readiness"), dict) else {}
    readiness = []
    for dim in BOARD_READINESS_DIMENSIONS:
        d = raw_scores.get(dim["id"]) if isinstance(raw_scores.get(dim["id"]), dict) else {}
        try:
            score = int(d.get("score"))
            score = max(1, min(5, score))
        except (TypeError, ValueError):
            score = None
        readiness.append({"id": dim["id"], "label": dim["label"], "score": score, "comment": _s(d.get("comment"), 300)})

    return {"compliance": compliance, "board_readiness": readiness, "summary": _s(raw.get("summary"), 800)}
