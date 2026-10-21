"""Validation and normalisation of data coming from the browser or the LLM."""
from .catalog import AUDIENCE_BY_ID, KINDS, LENGTHS

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
        "audience": raw.get("audience") if raw.get("audience") in AUDIENCE_BY_ID else "board",
        "length": raw.get("length") if raw.get("length") in LENGTHS else "mid",
        "source": raw.get("source") if raw.get("source") in SOURCES else "scratch",
        "template": _s(raw.get("template"), 60),
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
