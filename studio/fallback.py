"""Built-in rules used when the LLM is unavailable or returns something unusable.

They never invent facts: they produce a well-structured skeleton with
[placeholders] that the quality check then flags.
"""
import re

from .catalog import AUDIENCE_BY_ID, BOARD_READINESS_DIMENSIONS, BOARD_RULES, KINDS
from .checks import POLITICAL_RISK


def _ev(gap=""):
    return {"status": "needed", "source": "", "gap": gap or "Evidence needed"}


def storyline(brief, version):
    topic = (brief.get("topic") or "Untitled presentation").strip()
    decision = (brief.get("decision") or "").strip()
    ask = decision or "[state the decision you need]"
    s = {
        "title": {"kind": "title", "headline": topic, "body": [AUDIENCE_BY_ID.get(brief.get("audience"), AUDIENCE_BY_ID["executive"])["label"]],
                  "visual": "Cover", "notes": "Introduce the purpose of the session and the decision you will ask for.",
                  "evidence": {"status": "linked", "source": "Brief", "gap": ""}},
        "summary": {"kind": "summary", "headline": "[State the answer on %s in one sentence]" % topic,
                    "body": ["[Key message 1 with its headline figure]", "[Key message 2 with its headline figure]",
                             "[Key message 3 with its headline figure]", "We ask you to: " + ask],
                    "visual": "Three key messages", "notes": "Give the answer first. Then name the three reasons, and close with the ask.",
                    "evidence": _ev("Headline needs the conclusion")},
        "kpi": {"kind": "kpi", "headline": "Where we stand: [n] of [m] metrics are on track",
                "body": ["[Metric 1: actual vs target]", "[Metric 2: actual vs target]", "[Metric 3: actual vs target]", "[Metric 4: actual vs target]"],
                "visual": "Metric tiles vs target", "notes": "Point to the metrics that are off track; do not read every number.",
                "evidence": _ev("Metrics not provided")},
        "bars": {"kind": "bars", "headline": "What changed: [size and direction of the trend]",
                 "body": ["[Period-over-period change]", "[Where the change came from]", "[What it means for the plan]"],
                 "visual": "Column chart, actual vs plan", "notes": "Explain the size of the change and why it matters now.",
                 "evidence": _ev("Trend data not provided")},
        "driver": {"kind": "driver", "headline": "[Outcome] changed mainly because of [driver 1] and [driver 2]",
                   "body": ["[Driver 1 and its contribution]", "[Driver 2 and its contribution]", "[Driver 3 and its contribution]"],
                   "visual": "Driver tree", "notes": "Walk from the outcome to its biggest driver and say where you will act.",
                   "evidence": _ev("Driver analysis needs data")},
        "matrix": {"kind": "matrix", "headline": "[Recommended option] gives the best value for acceptable risk",
                   "body": ["Option A: [value, risk]", "Option B: [value, risk]", "Option C: [value, risk]", "Recommended: [option and why]"],
                   "visual": "2×2: value vs risk", "notes": "Show the options were considered fairly, then land on the recommendation.",
                   "evidence": _ev("Option assessment needed")},
        "decision": {"kind": "decision", "headline": "Decision required: " + ask,
                     "body": ["Context: [why this decision is needed now]", "Recommendation: " + ask,
                              "Impact: [benefit, cost and payback]", "Timing: [decision deadline]"],
                     "visual": "Ask, rationale and impact",
                     "notes": "State the ask plainly, then the impact of approving and of waiting.",
                     "evidence": {"status": "linked" if decision else "needed", "source": "Brief" if decision else "",
                                  "gap": "" if decision else "No decision stated"}},
        "roadmap": {"kind": "roadmap", "headline": "We deliver in three phases by [date]",
                    "body": ["Phase 1: [scope, owner, date]", "Phase 2: [scope, owner, date]", "Phase 3: [scope, owner, date]"],
                    "visual": "Phased timeline", "notes": "Highlight the milestones where leadership input is needed.",
                    "evidence": _ev("Plan dates and owners needed")},
        "risk": {"kind": "risk", "headline": "[Top risk] is the main risk; mitigation is in place",
                 "body": ["[Risk 1: likelihood, impact, owner]", "[Risk 2: likelihood, impact, owner]", "[Risk 3: likelihood, impact, owner]"],
                 "visual": "Likelihood × impact grid", "notes": "Be direct about the biggest risk and who owns it.",
                 "evidence": _ev("Risk assessment needed")},
        "appendix": {"kind": "table", "headline": "Appendix: supporting data and definitions",
                     "body": ["[Definitions]", "[Data sources and dates]", "[Detailed tables]"],
                     "visual": "Reference table", "notes": "Use only if asked.", "evidence": _ev("Supporting data needed")},
    }
    task = brief.get("task")
    length = brief.get("length", "mid")
    if task == "single" or version == "brief":
        order = ["decision" if decision else "summary"]
    elif version == "summary":
        order = ["title", "summary", "kpi", "matrix", "decision"]
    elif length == "short":
        order = ["summary", "decision"]
    else:
        order = ["title", "summary", "kpi", "driver", "matrix", "decision", "roadmap"]
    slides = [dict(s[k], body=list(s[k]["body"]), evidence=dict(s[k]["evidence"])) for k in order]
    return {"title": topic, "slides": slides}


# --------------------------------------------------------------------- advisor
_RULES = [
    ("driver", r"why|cause|increase|decrease|drop|rise|rose|fell|declin|driver|root", "Driver analysis",
     "Your message explains a change. A driver tree breaks the outcome into its causes and sizes each one, so leaders see where to act.",
     ["Headline that names the top driver", "Outcome on the left, 3–4 drivers in the middle", "Size each driver in points or %", "Highlight the driver you will act on"],
     "[Outcome] changed [x] pts, mainly because of [driver]"),
    ("matrix", r"compar|option|vendor|alternative|versus|\bvs\b|choose|select", "Options comparison",
     "You are weighing alternatives. A 2×2 or scored matrix shows the trade-off on the two criteria that matter and makes the recommendation obvious.",
     ["Headline that states the recommended option", "Pick the two criteria leaders care about", "Place each option and shade the recommendation", "One line on why the others lose"],
     "[Option] gives the best value at acceptable risk"),
    ("decision", r"approv|decid|decision|\bask\b|invest|fund|sign.?off|budget", "Decision brief",
     "You need a decision. A decision brief puts the ask first, then rationale, cost and impact, so leaders can decide in the room.",
     ["The ask as the headline", "Three-line rationale", "Investment, return and payback", "What happens if we wait"],
     "Approve [amount] for [initiative] to deliver [benefit] by [date]"),
    ("roadmap", r"plan|roadmap|timeline|phase|month|transform|rollout|milestone", "Phased roadmap",
     "Your message is about sequence and timing. A phased roadmap shows what happens when, who owns it and where the decision gates are.",
     ["Headline with the end state and date", "3–4 phases on one timeline", "Milestones and owners per phase", "Mark the gates that need leadership input"],
     "We reach [end state] by [date] in three releases"),
    ("risk", r"risk|threat|issue|concern|exposure|mitigat", "Risk heat map",
     "You are showing exposure. A likelihood-by-impact grid with named mitigations shows which risks deserve attention.",
     ["Headline that names the top risk", "Plot risks on likelihood × impact", "Mitigation and owner for the top three", "Residual risk after mitigation"],
     "[Risk] is the only risk above tolerance; mitigation is in place"),
    ("kpi", r"kpi|metric|status|scorecard|dashboard|perform|track", "KPI scorecard",
     "Your message is a status update. A scorecard shows each metric against target with a clear on-track or off-track signal.",
     ["Headline that names what is off track", "4–6 metrics with target and actual", "Status colour per metric", "One line on each exception"],
     "[n] of [m] KPIs are on track; [KPI] needs action"),
]
_FALLBACK_RULE = ("summary", "", "Key message with proof points",
                  "Your message is a single argument. Lead with the conclusion and support it with three proof points, each with one number.",
                  ["Conclusion as the headline", "Three proof points", "One figure per point", "Source line at the bottom"],
                  "[Your conclusion in one sentence]")


def advise(message):
    hits = [r for r in _RULES if re.search(r[1], message, re.I)]
    main = hits[0] if hits else _FALLBACK_RULE
    rest = [r for r in hits if r is not main] + [r for r in _RULES if r is not main and r not in hits]
    return {
        "primary": {"kind": main[0], "name": main[2], "why": main[3], "steps": list(main[4]), "example": main[5]},
        "alternates": [{"kind": r[0], "name": r[2], "why": r[3].split(". ")[0] + "."} for r in rest[:2]],
    }


# --------------------------------------------------------------------- Q&A
def qa(brief, slides):
    decision = (brief.get("decision") or "").strip()
    topic = brief.get("topic") or "this topic"
    qs = [
        {"question": "What is the single most important point about %s?" % topic,
         "answer": "Answer with the summary headline in one sentence, then state the ask.", "evidence": "Summary slide"},
        {"question": "How confident are you in these numbers?",
         "answer": "Name the data source, its date and the main assumption. Offer the appendix for detail.", "evidence": "Appendix and sources"},
        {"question": ("What happens if we do not %s?" % (decision[0].lower() + decision[1:])) if decision else "What exactly are you asking us to decide?",
         "answer": "Quantify the cost of waiting and the date by which a decision is needed." if decision else "State the decision, the owner and the deadline.",
         "evidence": "Decision slide"},
        {"question": "What are the biggest risks, and who owns them?",
         "answer": "Cover the top two risks, their likelihood and the named owner of each mitigation.", "evidence": "Risk slide"},
        {"question": "What alternatives did you consider?",
         "answer": "Summarise the options and the criteria used, then explain why the recommendation wins.", "evidence": "Options slide"},
    ]
    missing = [i + 1 for i, s in enumerate(slides) if (s.get("evidence") or {}).get("status") != "linked"]
    if missing:
        qs[1]["evidence"] = "Prepare sources for slides " + ", ".join(map(str, missing[:6]))
    return {"questions": qs}


# --------------------------------------------------------------------- headline
_TOPIC_PREFIX = re.compile(r"^(overview of|update on|summary of|introduction to|review of)\s+", re.I)


def sharpen(headline):
    h = _TOPIC_PREFIX.sub("", (headline or "").strip()).rstrip(".")
    return h[:1].upper() + h[1:] if h else headline


# --------------------------------------------------------------------- briefing
def briefing(brief, title, slides):
    heads = [s.get("headline", "") for s in slides if s.get("kind") not in ("title",)]
    decision = (brief.get("decision") or "").strip() or "[State the decision required]"
    lines = ["## Context", "This pre-read supports the session on %s." % (brief.get("topic") or title), "",
             "## The answer", heads[0] if heads else "[State the answer]", "",
             "## Key evidence"]
    lines += ["- " + h for h in heads[1:6]] or ["- [Evidence]"]
    lines += ["", "## Decision required", decision, "", "## Next steps", "- [Next step, owner, date]"]
    return "\n".join(lines)


def kind_name(kind):
    return KINDS.get(kind, kind)


# --------------------------------------------------------------------- GEC/GIC board assessment
_WEAK_TITLE = re.compile(r"^(overview|update|summary|introduction|agenda|review|background|status|analysis)\b", re.I)
_AGENDA_LIKE = re.compile(r"agenda|background|introduction", re.I)
_POLITICAL_RISK = POLITICAL_RISK


def _nums(items):
    items = [str(n) for n in items]
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def board_assessment(brief, slides, ctx):
    """Structural, non-judgemental checks only. Title/message quality, board readiness and
    everything requiring external evidence need the AI model; this is clearly labelled as
    reduced-capability output via the 'rules' source the caller attaches."""
    content = [s for s in slides if s.get("kind") != "title"]
    lead, last = (content[0], content[-1]) if content else (None, None)
    decision_text = bool((brief.get("decision") or "").strip())
    ook = (ctx or {}).get("ook_investment", "")
    results = {}

    minutes = round(len(slides) * 1.5, 1)
    results["PRES-01"] = ("PASS" if minutes <= 15 else "FAIL",
                          "Built-in estimate: ~%s minutes for %d slides (not a measured timing)." % (minutes, len(slides)),
                          "" if minutes <= 15 else "Cut slides or move detail to backup to fit the 15-minute limit.")

    if not lead:
        results["PRES-03"] = ("FAIL", "The deck has no content slides.", "Add an opening slide that states the requested action.")
    elif lead["kind"] in ("summary", "decision") and decision_text:
        results["PRES-03"] = ("PASS", "The opening content slide (%s) leads with the ask." % lead["kind"], "")
    else:
        results["PRES-03"] = ("WARNING", "The opening content slide is a %s slide; the requested GEC/GIC action was not confirmed." % (lead["kind"] if lead else "?"),
                              "State explicitly what is required from GEC/GIC (approval, guidance or information).")

    agenda = [i + 1 for i, s in enumerate(slides) if _AGENDA_LIKE.search(s.get("headline", ""))]
    results["PRES-04"] = (("WARNING", "Slide%s %s read as agenda or background." % ("s" if len(agenda) > 1 else "", _nums(agenda)), "Remove or move to backup material.")
                           if agenda else ("PASS", "No agenda or background-labelled slides detected.", ""))

    weak = [i + 1 for i, s in enumerate(slides) if s.get("kind") != "title" and _WEAK_TITLE.search(s.get("headline", ""))]
    results["PRES-05"] = (("WARNING", "Slide%s %s use a topic label rather than a key message (partial check only; AI review recommended for all titles)."
                           % ("s" if len(weak) > 1 else "", _nums(weak)), "Rewrite as the slide's key finding.")
                           if weak else ("WARNING", "No obvious topic-label titles found, but this built-in check cannot judge title quality the way the AI model can.", ""))

    results["PRES-07"] = ("NOT VERIFIABLE", "A visual progress gauge cannot be confirmed without AI/visual review.", "")

    if not last:
        results["PRES-08"] = ("FAIL", "The deck has no content slides.", "Add a closing slide confirming the action sought.")
    elif last["kind"] == "decision":
        results["PRES-08"] = ("PASS", "The final content slide is a decision slide.", "")
    else:
        results["PRES-08"] = ("WARNING", "The final content slide is a %s slide." % last["kind"], "Close with a decision slide restating the ask.")

    ook_mentioned = any(_POLITICAL_RISK.search(s.get("headline", "") + " " + " ".join(s.get("body") or [])) for s in slides)
    if ook == "no":
        results["PRES-09"] = results["COMP-09"] = ("NOT APPLICABLE", "Not an OOK investment.", "")
    elif ook == "yes":
        results["PRES-09"] = (("PASS", "Political Risk Framework content found.", "") if ook_mentioned else
                               ("FAIL", "No Political Risk Framework content found.", "Add the Political Risk Framework section."))
        results["COMP-09"] = ("NOT VERIFIABLE", "Consultation with the Investment Guidelines Group cannot be confirmed from the presentation.", "Provide confirmation of consultation.")
    else:
        results["PRES-09"] = results["COMP-09"] = ("WARNING", "OOK investment status was not specified.", "Specify whether this is an OOK investment.")

    compliance = []
    for rule in BOARD_RULES:
        rid = rule["id"]
        if rid == "SUB-01":
            continue  # computed separately in services.py
        result, evidence, action = results.get(rid, ("NOT VERIFIABLE",
            "Requires information outside the presentation (submission records, sign-offs or consultations).",
            "Confirm and document separately."))
        compliance.append({"id": rid, "category": rule["category"], "requirement": rule["requirement"],
                            "critical": bool(rule.get("critical")), "result": result, "evidence": evidence, "action": action})

    readiness = [{"id": d["id"], "label": d["label"], "score": None, "comment": "Needs the AI model; not scored by built-in rules."}
                 for d in BOARD_READINESS_DIMENSIONS]
    return {"compliance": compliance, "board_readiness": readiness,
            "summary": "Built-in rules give a partial, structural compliance check only. Connect the AI model for title-quality and board-readiness scoring."}
