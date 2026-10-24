"""A stand-in for the DeepSeek server, for testing without the real model.

Speaks the OpenAI-compatible /v1/models and /v1/chat/completions API and returns
canned JSON that matches what the studio's prompts ask for.

    Windows:  .venv\\Scripts\\python tests\\mock_llm.py 8001
              set STUDIO_LLM_BASE_URL=http://127.0.0.1:8001/v1 && .venv\\Scripts\\python server.py
    Or in VS Code: Run and Debug > "Studio + mock AI".
"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# How the mock "simplifies" a slide body: "merge" folds it into three lines and keeps every word
# (a good model); "drop" keeps the first line only (the content loss seen in the 23 Oct test).
TRANSFORM_MODE = "merge"
TRANSFORM_CALLS = []   # slide indices of every transform request, so tests can see retries
SHARPEN_REPLIES = []   # headlines to return first, before the default good one


def _simplify(body):
    if TRANSFORM_MODE == "drop":
        return body[:1]
    k = min(3, len(body))
    size = -(-len(body) // k) if k else 0
    return ["; ".join(body[i:i + size]) for i in range(0, len(body), size)] if k else []


def _parse_brief_block(user_content):
    """Pull the {"topic": ..., "decision_required": ..., ...} object out of the
    BRIEF\\n{json} block the real prompts.py puts in the user message."""
    marker = "BRIEF\n"
    i = user_content.find(marker)
    if i < 0:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(user_content[i + len(marker):])
        return obj
    except ValueError:
        return {}


def _dynamic_storyline(brief):
    """Build a storyline out of whatever the caller actually typed, so the mock
    proves the brief -> prompt -> response pipeline instead of always echoing demo data."""
    topic = (brief.get("topic") or "").strip() or "Presentation"
    decision = (brief.get("decision_required") or "").strip()
    facts = (brief.get("key_facts") or "").strip()
    audience = (brief.get("audience") or "Senior leadership").strip()
    fact_bullets = [f.strip() for f in re.split(r"[.\n]", facts) if f.strip()][:4]
    if not facts:
        # what a real model did with no facts in the 23 Oct test (D-09): one slide, chatter in the notes
        return {"title": topic, "slides": [{"kind": "summary", "headline": "Facts are needed to build " + topic,
                "body": ["Share the key figures"], "notes": "I cannot build this storyline without data. Please share the facts.",
                "evidence": {"status": "linked", "source": "SOURCE DOCUMENTS"}}]}

    slides = [{"kind": "title", "headline": topic, "body": [audience], "visual": "Cover", "notes": "Welcome.",
               "evidence": {"status": "linked", "source": "Brief", "gap": ""}}]

    summary_body = list(fact_bullets[:3]) or ["[finding 1]", "[finding 2]", "[finding 3]"]
    if decision:
        summary_body.append("We ask you to " + decision[0].lower() + decision[1:])
    slides.append({"kind": "summary", "headline": "Key message: " + topic, "body": summary_body,
                    "visual": "Three key messages", "notes": "Lead with the answer.",
                    "evidence": {"status": "linked", "source": "Key facts", "gap": ""} if fact_bullets
                    else {"status": "needed", "source": "", "gap": "Key facts not provided"}})

    if len(fact_bullets) >= 2:
        slides.append({"kind": "driver", "headline": "What is driving this: " + fact_bullets[0][:80],
                        "body": fact_bullets[:3], "visual": "Driver tree", "notes": "Walk through each driver.",
                        "evidence": {"status": "linked", "source": "Key facts", "gap": ""}})

    if decision:
        slides.append({"kind": "decision", "headline": "Decision required: " + decision,
                        "body": ["Context: " + (fact_bullets[0] if fact_bullets else "[context]"),
                                 "Recommendation: " + decision, "Impact: [impact]", "Timing: [decide by date]"],
                        "visual": "Ask, rationale, impact", "notes": "State the ask clearly.",
                        "evidence": {"status": "linked", "source": "Brief", "gap": ""}})

    slides.append({"kind": "roadmap", "headline": "Next steps for " + topic,
                    "body": ["Wave 1: [action], [date]", "Wave 2: [action], [date]", "Wave 3: [action], [date]"],
                    "visual": "Phased timeline", "notes": "Outline the path forward.",
                    "evidence": {"status": "needed", "source": "", "gap": "Timeline not provided"}})
    return {"title": topic, "slides": slides}


STORYLINE = {
    "title": "Q3 Business Performance Review",
    "slides": [
        {"kind": "title", "headline": "Q3 Business Performance Review", "body": ["CEO / Board"], "visual": "Cover", "notes": "Welcome.",
         "evidence": {"status": "linked", "source": "Brief", "gap": ""}},
        {"kind": "summary", "headline": "Q3 revenue beat plan by 4%, but margin slipped 1.8 pts",
         "body": ["Revenue 4% above plan on enterprise growth", "Gross margin down 1.8 pts on input costs", "We ask you to approve a 3% mid-market price increase"],
         "visual": "Three key messages", "notes": "Lead with the answer.", "evidence": {"status": "linked", "source": "Q3_financials.xlsx", "gap": ""}},
        {"kind": "driver", "headline": "Margin fell mainly because of input costs and deeper discounts",
         "body": ["Input costs: [x] pts", "Discount depth: [y] pts", "Mix: [z] pts"], "visual": "Margin bridge",
         "notes": "Walk the bridge.", "evidence": {"status": "needed", "source": "", "gap": "Discount data by segment"}},
        {"kind": "decision", "headline": "Decision required: approve a 3% mid-market price increase from January",
         "body": ["Context: margin pressure continues", "Recommendation: 3% increase in mid-market", "Impact: recovers most of the margin gap", "Timing: decide by 15 November"],
         "visual": "Ask, rationale, impact", "notes": "State the ask.", "evidence": {"status": "linked", "source": "Brief", "gap": ""}},
        {"kind": "roadmap", "headline": "Roll out in three waves with a churn checkpoint after each",
         "body": ["Wave 1: pilot region, January", "Wave 2: two regions, March", "Wave 3: all mid-market, May"], "visual": "Phased timeline",
         "notes": "Gates protect against churn.", "evidence": {"status": "linked", "source": "Pricing plan", "gap": ""}},
    ],
}
QA = {"questions": [{"question": "Why raise prices when revenue beat plan?", "answer": "Growth came from volume, not price.", "evidence": "Slides 2–3"}]}
ADVISE = {"primary": {"kind": "driver", "name": "Driver analysis", "why": "Explains causes. Sizes each driver.",
                      "steps": ["Headline", "Outcome left", "Drivers right", "Highlight"], "example": "Turnover rose [x] pts on early-tenure exits"},
          "alternates": [{"kind": "bars", "name": "Trend chart", "why": "Shows the change over time."},
                         {"kind": "table", "name": "Exit reasons table", "why": "Lists reasons by count."}]}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._send({"data": [{"id": "deepseek-4.1-flash"}]})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        system = req["messages"][0]["content"]
        if "storyline" in system or "answer-first storyline" in system:
            brief = _parse_brief_block(req["messages"][1]["content"])
            out = _dynamic_storyline(brief) if brief.get("topic") else STORYLINE
        elif "hardest questions" in system:
            out = QA
        elif "recommend the single best slide" in system:
            out = ADVISE
        elif "Rewrite the slide headline" in system:
            out = {"headline": SHARPEN_REPLIES.pop(0) if SHARPEN_REPLIES else "Margin fell 1.8 pts, driven by input costs"}
        elif "improving existing slides" in system:
            slides = json.loads(req["messages"][1]["content"].split("SLIDES\n", 1)[1].split("\n\nYOUR PREVIOUS", 1)[0])
            TRANSFORM_CALLS.append([x["index"] for x in slides])
            out = {"slides": [{"index": x["index"], "title": (x["title"] + ": the key finding")[:120],
                               "body": _simplify(x["body"]) if "Simplify" in system else None,
                               "change": "Headline rewritten"} for x in slides]}
        elif "Compliance Reviewer" in system:
            # an over-generous reviewer: passes everything and quotes the brief (test report D-02)
            out = {"compliance": [{"id": "PRES-08", "result": "PASS", "evidence": "Closing confirms the decision.", "action": ""}],
                   "board_readiness": {d: {"score": 5 if d == "decision_clarity" else 4, "comment": "Good."} for d in (
                       "decision_clarity", "executive_relevance", "message_titles", "evidence", "conciseness",
                       "decision_flow", "technical_depth", "consistency", "risk_visibility", "closing_decision")},
                   "summary": "Ready."}
        elif "pre-read" in system:
            out = {"brief": "## Context\nTest brief."}
        else:
            out = {}
        content = "```json\n" + json.dumps(out) + "\n```"   # fenced on purpose: the client must cope
        self._send({"choices": [{"message": {"role": "assistant", "content": content}}]})


def serve(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    return srv


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    srv = serve(port)
    print("Mock LLM listening on http://127.0.0.1:%d/v1" % port, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
