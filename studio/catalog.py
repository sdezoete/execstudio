"""Reference data: slide kinds, audiences, classifications, templates, repository and toolkit.

Templates, repository and toolkit live in data/*.json so the presentation team can
maintain them without touching code.
"""
import json

from .config import ROOT

DATA = ROOT / "data"

KINDS = {
    "title": "Title",
    "summary": "Answer-first summary",
    "kpi": "KPI scorecard",
    "bars": "Variance chart",
    "driver": "Driver tree",
    "matrix": "Options matrix",
    "decision": "Decision brief",
    "roadmap": "Roadmap",
    "risk": "Risk heat map",
    "table": "Data table",
}

AUDIENCES = [
    {"id": "board", "label": "CEO / Board", "short": "CEO / Board",
     "guidance": "CEO and board members. Lead with the decision and its business impact. "
                 "Strategic, concise, no operational detail; move detail to the appendix. Ten slides at most."},
    {"id": "evp", "label": "EVP / Senior leadership", "short": "EVP / Senior",
     "guidance": "Executive vice presidents. Answer first, then the evidence and trade-offs. "
                 "Show cross-functional impact and the resources required."},
    {"id": "functional", "label": "Functional management", "short": "Functional",
     "guidance": "Functional managers. More detail on plans, owners, timelines and metrics. "
                 "Make actions and responsibilities explicit."},
    {"id": "operational", "label": "Operational teams", "short": "Operational",
     "guidance": "Operational teams. Practical and specific: what changes, who does what, by when, "
                 "and how success is measured. Plain language."},
]
AUDIENCE_BY_ID = {a["id"]: a for a in AUDIENCES}

CLASSIFICATIONS = ["Public", "Internal", "Confidential", "Restricted"]
DEFAULT_CLASSIFICATION = "Confidential"

LENGTHS = {"short": (1, 3), "mid": (5, 10), "long": (10, 20)}


def _load(name, default):
    path = DATA / name
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def templates():
    return _load("templates.json", {"default": "corporate", "templates": [
        {"id": "corporate", "name": "Corporate Master", "accent": "1F47C9", "ink": "1A2421",
         "muted": "5A6763", "tile": "EDF1EF", "warn": "D9822B", "font": "Calibri"}]})


def template(tid):
    data = templates()
    for t in data["templates"]:
        if t["id"] == tid:
            return t
    return next(t for t in data["templates"] if t["id"] == data["default"])


def repository():
    return _load("repository.json", {"items": []})


def toolkit():
    return _load("toolkit.json", {"items": []})


def slide_range(length, version, task):
    """Inclusive (min, max) slide count for a request."""
    if task == "single" or version == "brief":
        return 1, 1
    if version == "summary":
        return 4, 6
    return LENGTHS.get(length, LENGTHS["mid"])
