"""Reference data: slide kinds, audiences, templates, repository and toolkit.

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
    {"id": "executive", "label": "Executive", "short": "Executive",
     "guidance": "CEO, board and senior leadership. Lead with the decision and its business impact; "
                 "answer first, then the evidence and trade-offs. Strategic and concise -- move "
                 "operational detail to the appendix. Ten slides at most."},
    {"id": "operational", "label": "Operational", "short": "Operational",
     "guidance": "Functional and operational teams. Detailed plans, owners, timelines and metrics; "
                 "practical and specific about what changes, who does what, by when, and how success "
                 "is measured. Plain language."},
]
AUDIENCE_BY_ID = {a["id"]: a for a in AUDIENCES}

LENGTHS = {"short": (1, 3), "mid": (5, 10)}


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


# --------------------------------------------------------------- GEC/GIC board assessment
PRESENTATION_TYPES = {"cms": "CMS", "transaction": "Transactions / M&A / Divestiture", "other": "Other"}
STAGE_GATES = {"gate0": "Gate 0", "gate1": "Gate I", "gate2": "Gate II", "gate3": "Gate III",
               "gate_alt": "Gate Alternative Selection", "na": "N/A"}

# SUB-01 is computed deterministically from the submission/meeting dates (see services.py);
# it is listed here for the UI table but is never asked of the LLM or the rule-based fallback.
BOARD_RULES = [
    {"id": "SUB-01", "category": "Submission process", "requirement": "Submitted 6 or more business days before the meeting"},
    {"id": "SUB-02", "category": "Submission process", "requirement": "External presenters and visitors are identified by name"},
    {"id": "SUB-03", "category": "Submission process", "requirement": "External visitor ID documents submitted (G.I. 710.014)"},
    {"id": "PRES-01", "category": "Presentation", "requirement": "Delivery time is 15 minutes or less"},
    {"id": "PRES-02", "category": "Presentation", "requirement": "Presenter completed Executive Presentation training or coaching"},
    {"id": "PRES-03", "category": "Presentation", "requirement": "Opening slide clearly states the action required from GEC/GIC", "critical": True},
    {"id": "PRES-04", "category": "Presentation", "requirement": "No unnecessary agenda slides or excessive background"},
    {"id": "PRES-05", "category": "Presentation", "requirement": "Every slide title states its key message, not just its subject"},
    {"id": "PRES-06", "category": "Presentation", "requirement": "Correct GEC/GIC template and required sections are used"},
    {"id": "PRES-07", "category": "Presentation", "requirement": "Presentation includes a progress gauge"},
    {"id": "PRES-08", "category": "Presentation", "requirement": "Closing slide confirms the action(s) sought from GEC/GIC", "critical": True},
    {"id": "PRES-09", "category": "Presentation", "requirement": "OOK investments include the Political Risk Framework"},
    {"id": "COMP-01", "category": "Engagement & compliance", "requirement": "Strategic Fit jointly developed with and signed off by Corporate Strategy"},
    {"id": "COMP-02", "category": "Engagement & compliance", "requirement": "Emerging Strategies & Investment Group (SMA) consulted on economic analysis"},
    {"id": "COMP-03", "category": "Engagement & compliance", "requirement": "Investment Guidelines Group (SMA) consulted on stochastic analysis / portfolio optimization"},
    {"id": "COMP-04", "category": "Engagement & compliance", "requirement": "Emerging Strategies & Investment Group consulted on risk assessment (CP-11)"},
    {"id": "COMP-05", "category": "Engagement & compliance", "requirement": "Law organization consulted for items requiring legal review"},
    {"id": "COMP-06", "category": "Engagement & compliance", "requirement": "Finance and Treasury consulted on the transaction's economic model"},
    {"id": "COMP-07", "category": "Engagement & compliance", "requirement": "Capital Program items meet CMS gate requirements"},
    {"id": "COMP-08", "category": "Engagement & compliance", "requirement": "Transaction items: NBD consulted and GI-30.001 gate requirements met"},
    {"id": "COMP-09", "category": "Engagement & compliance", "requirement": "OOK investments: Investment Guidelines Group consulted on the political framework"},
]
BOARD_RULES_BY_ID = {r["id"]: r for r in BOARD_RULES}

# These depend on submission paperwork, sign-offs or consultations this app has no record of.
# They can never be marked PASS/FAIL from presentation content alone (see services._clamp_external).
BOARD_EXTERNAL_ONLY = {"SUB-02", "SUB-03", "PRES-02", "PRES-06",
                        "COMP-01", "COMP-02", "COMP-03", "COMP-04", "COMP-05", "COMP-06", "COMP-07", "COMP-08", "COMP-09"}

BOARD_READINESS_DIMENSIONS = [
    {"id": "decision_clarity", "label": "Decision clarity"},
    {"id": "executive_relevance", "label": "Executive relevance"},
    {"id": "message_titles", "label": "Message titles"},
    {"id": "evidence", "label": "Evidence"},
    {"id": "conciseness", "label": "Conciseness"},
    {"id": "decision_flow", "label": "Decision flow"},
    {"id": "technical_depth", "label": "Technical depth"},
    {"id": "consistency", "label": "Consistency"},
    {"id": "risk_visibility", "label": "Risk visibility"},
    {"id": "closing_decision", "label": "Closing decision"},
]
