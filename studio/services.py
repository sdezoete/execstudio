"""Business logic behind each API endpoint.

Every AI feature tries the LLM first and falls back to the built-in rules, so
the studio keeps working (with clearly labelled output) if the model is down.
"""
import datetime as _dt
import json
import logging
import re
import threading
import time
from pathlib import Path

from . import catalog, fallback, prompts, review, schema
from . import slides as slide_engine
from .checks import clean_storyline, headline_problem, rewrite_problem
from .config import ROOT
from .extract import PDF_SUPPORTED, ExtractError, extract
from .llm import LLMClient, LLMError
from .workspace import Workspace

try:
    from .slides import deck as deck_ops
    from .slides.deck import DeckError
except ImportError:  # python-pptx not installed: deck transformation unavailable
    deck_ops = None

    class DeckError(Exception):
        pass

log = logging.getLogger("studio")


class Studio:
    def __init__(self, cfg):
        self.cfg = cfg
        self.llm = LLMClient(cfg)
        self._audit_lock = threading.Lock()
        path = cfg.get("audit_log")
        self.audit_path = (ROOT / path) if path and not Path(path).is_absolute() else (Path(path) if path else None)
        if self.audit_path:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        work = Path(cfg.get("work_dir") or "work")
        self.work = Workspace(work if work.is_absolute() else ROOT / work, int(cfg.get("work_retention_hours", 24)))

    # ------------------------------------------------------------ helpers
    def audit(self, action, brief=None, **extra):
        """Metadata only: never slide text, facts or file contents."""
        if not self.audit_path:
            return
        rec = {"ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"), "action": action}
        if brief:
            rec.update({"template": brief.get("template"),
                        "audience": brief.get("audience"), "task": brief.get("task")})
        rec.update(extra)
        with self._audit_lock, open(self.audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _ai(self, action, call, rules, brief=None):
        """Run call() against the LLM; on any failure use rules(). Returns (result, meta)."""
        t0 = time.time()
        try:
            result = call()
            meta = {"source": "llm", "model": self.llm.display_name}
        except (LLMError, ValueError, KeyError, TypeError) as e:
            log.warning("%s: falling back to built-in rules (%s)", action, e)
            result = rules()
            meta = {"source": "rules", "warning": "The AI service was unavailable or its answer could not be used (%s). "
                                                  "Built-in rules were used instead." % str(e).rstrip(".")}
        self.audit(action, brief, source=meta["source"], ms=int((time.time() - t0) * 1000))
        return result, meta

    def _context(self, brief, uploaded):
        parts = []
        if brief.get("facts"):
            parts.append("### Key facts provided by the presenter\n" + brief["facts"])
        if uploaded:
            parts.append(uploaded)
        text = "\n\n".join(parts)
        limit = int(self.cfg["max_context_chars"])
        if len(text) > limit:
            text = text[:limit] + "\n[...remaining material omitted for length]"
        return text

    # ------------------------------------------------------------ endpoints
    def meta(self):
        t = catalog.templates()
        return {
            "audiences": [{"id": a["id"], "label": a["label"], "short": a["short"]} for a in catalog.AUDIENCES],
            "templates": [{"id": x["id"], "name": x["name"]} for x in t["templates"]],
            "default_template": t["default"],
            "kinds": catalog.KINDS,
        }

    def health(self):
        return {"status": "ok", "llm": self.llm.health(),
                "pptx": dict(slide_engine.status(), transform=deck_ops is not None), "pdf": PDF_SUPPORTED}

    def storyline(self, payload):
        b = schema.brief(payload.get("brief"))
        if not b["topic"]:
            raise schema.BadRequest("Add a presentation topic.")
        version = payload.get("version") if payload.get("version") in schema.VERSIONS else "full"
        ctx = self._context(b, str(payload.get("context") or ""))
        lo, hi = catalog.slide_range(b["length"], version, b["task"])

        def call():
            system, user = prompts.storyline(b, version, ctx)
            data = schema.storyline(self.llm.chat_json(system, user), b["topic"])
            data["slides"] = clean_storyline(data["slides"][:max(hi, 1)], bool(ctx))
            if len(data["slides"]) < lo:
                # e.g. one "please send me facts" slide when no facts were given (test report D-09)
                raise ValueError("the AI returned %d slide%s, fewer than the %d asked for"
                                 % (len(data["slides"]), "" if len(data["slides"]) == 1 else "s", lo))
            return data

        result, meta = self._ai("storyline", call, lambda: fallback.storyline(b, version), b)
        result.update(meta)
        result["version"] = version
        return result

    def review(self, payload):
        b = schema.brief(payload.get("brief"))
        slides = schema.slides(payload.get("slides"))
        if not slides:
            raise schema.BadRequest("There are no slides to check.")
        return review.run(b, slides)

    def qa(self, payload):
        b = schema.brief(payload.get("brief"))
        slides = schema.slides(payload.get("slides"))

        def call():
            system, user = prompts.qa(b, slides)
            data = self.llm.chat_json(system, user)
            qs = []
            for q in data.get("questions") or []:
                if isinstance(q, dict) and q.get("question"):
                    qs.append({"question": str(q["question"])[:400], "answer": str(q.get("answer", ""))[:1200],
                               "evidence": str(q.get("evidence", ""))[:300]})
            if not qs:
                raise ValueError("no questions returned")
            return {"questions": qs[:8]}

        result, meta = self._ai("qa", call, lambda: fallback.qa(b, slides), b)
        result.update(meta)
        return result

    def board_assessment(self, payload):
        b = schema.brief(payload.get("brief"))
        slides = schema.slides(payload.get("slides"))
        if not slides:
            raise schema.BadRequest("There are no slides to assess.")
        ctx = schema.board_context(payload.get("context"))

        def call():
            system, user = prompts.board_assessment(b, slides, ctx)
            return schema.board_result(self.llm.chat_json(system, user, max_tokens=6000))

        result, meta = self._ai("board_assessment", call, lambda: fallback.board_assessment(b, slides, ctx), b)
        _enforce_decision_slide(result, slides)
        result["compliance"].insert(0, _sub01(ctx))
        result.update(meta)
        return result

    def advise(self, payload):
        message = str(payload.get("message") or "").strip()[:1500]
        if not message:
            raise schema.BadRequest("Describe the message you want the slide to communicate.")
        b = payload.get("brief") if isinstance(payload.get("brief"), dict) else {}

        def call():
            system, user = prompts.advise(message, b)
            data = self.llm.chat_json(system, user)
            p = data["primary"]
            primary = {"kind": p["kind"] if p.get("kind") in catalog.KINDS else "summary",
                       "name": str(p["name"])[:80], "why": str(p.get("why", ""))[:600],
                       "steps": [str(x)[:160] for x in (p.get("steps") or [])][:6],
                       "example": str(p.get("example", ""))[:200]}
            alts = []
            for a in data.get("alternates") or []:
                if isinstance(a, dict) and a.get("name"):
                    alts.append({"kind": a.get("kind") if a.get("kind") in catalog.KINDS else "summary",
                                 "name": str(a["name"])[:80], "why": str(a.get("why", ""))[:300]})
            return {"primary": primary, "alternates": alts[:2]}

        result, meta = self._ai("advise", call, lambda: fallback.advise(message))
        result.update(meta)
        return result

    def sharpen(self, payload):
        headline = str(payload.get("headline") or "").strip()[:300]
        if not headline:
            raise schema.BadRequest("The headline is empty.")
        body = [str(x)[:300] for x in (payload.get("body") or [])][:8]
        b = payload.get("brief") if isinstance(payload.get("brief"), dict) else {}

        def call():
            # held to Quality check's own rules: one retry with the reason, then the built-in rules
            rejected = None
            for _attempt in range(2):
                system, user = prompts.sharpen(headline, body, b, rejected)
                h = str(self.llm.chat_json(system, user, max_tokens=300)["headline"]).strip()
                problem = headline_problem(h)
                if not problem:
                    return {"headline": h[:300]}
                rejected = (h, problem)
            raise ValueError("sharpened headline still fails: " + rejected[1])

        result, meta = self._ai("sharpen", call, lambda: {"headline": fallback.sharpen(headline)})
        result.update(meta)
        return result

    def extract(self, name, data):
        name = Path(name or "upload").name[:200]
        try:
            text = extract(name, data)
        except ExtractError:
            raise
        except Exception as e:  # noqa: BLE001  (corrupt files raise many different errors)
            log.exception("extract failed for %s", name)
            raise ExtractError("This file could not be read. Check it opens in Office and try again.") from e
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        limit = int(self.cfg["max_context_chars"])
        truncated = len(text) > limit
        if not text:
            raise ExtractError("No readable text was found in this file.")
        self.audit("extract", None, ext=name.rsplit(".", 1)[-1].lower(), chars=len(text))
        return {"name": name, "chars": len(text), "truncated": truncated, "text": text[:limit]}

    def _meta(self, b, title=""):
        """Returns (tpl, meta, upload). upload is None for a library template, or
        (file_bytes, is_potx) when the brief points at an ad-hoc uploaded one."""
        fid = (b.get("template_file") or "").strip()
        if fid:
            try:
                data, name = self.work.get(fid)
            except KeyError as e:
                raise schema.BadRequest("That uploaded template has expired. Upload it again.") from e
            is_potx = name.lower().endswith(".potx")
            tpl = dict(catalog.template(""), **slide_engine.theme_colors(data))  # house palette as the base, overridden by whatever the theme carries
            tpl["name"] = Path(name).stem[:60] or "Uploaded template"
            tpl["file"] = None
            meta = {"template_name": tpl["name"], "title": title,
                    "audience": catalog.AUDIENCE_BY_ID[b["audience"]]["label"],
                    "date": _dt.date.today().strftime("%d %B %Y")}
            return tpl, meta, (data, is_potx)
        tpl = catalog.template(b["template"])
        return tpl, {"template_name": tpl["name"], "title": title,
                     "audience": catalog.AUDIENCE_BY_ID[b["audience"]]["label"],
                     "date": _dt.date.today().strftime("%d %B %Y")}, None

    def template_upload(self, name, data):
        """Store an ad-hoc uploaded .pptx/.potx to use as this brief's template, instead of
        picking one from the library. Validated once here; theme colours are re-read (cheaply,
        never raising) from the stored bytes on every export via _meta()."""
        name = Path(name or "template.pptx").name[:200]
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in ("pptx", "potx"):
            raise schema.BadRequest("Upload a .pptx or .potx file.")
        if not slide_engine.supports_custom_template():
            raise schema.BadRequest("Using your own template needs python-pptx on the server. See README: Offline install.")
        try:
            slide_engine.validate_uploaded_template(data, ext == "potx")
        except ValueError as e:
            raise schema.BadRequest("This file could not be opened as a PowerPoint template. Check it opens in PowerPoint and try again.") from e
        fid = self.work.put(data, name)
        self.audit("template_upload", None, ext=ext)
        return {"template_file": fid, "name": name, "colors": slide_engine.theme_colors(data)}

    def export_pptx(self, payload):
        b = schema.brief(payload.get("brief"))
        slides = schema.slides(payload.get("slides"))
        if not slides:
            raise schema.BadRequest("There are no slides to export.")
        title = str(payload.get("title") or b["topic"] or "Presentation")[:200]
        tpl, meta, upload = self._meta(b, title)
        template_bytes, template_is_potx = upload if upload else (None, False)
        data = slide_engine.build(title, slides, meta, tpl, template_bytes, template_is_potx)
        self.audit("export_pptx", b, slides=len(slides), engine=slide_engine.ENGINE)
        moved = [(i, len(s["overflow"])) for i, s in enumerate(slides, 1) if s.get("overflow")]
        notice = ""
        if moved:
            notice = "%d point%s did not fit the layout on slide%s %s and moved to the speaker notes." % (
                sum(n for _, n in moved), "" if sum(n for _, n in moved) == 1 else "s",
                "" if len(moved) == 1 else "s", ", ".join(str(i) for i, _ in moved))
        return _filename(title, "pptx"), data, notice

    # ------------------------------------------------------------ existing decks
    def deck_upload(self, name, data):
        name = Path(name or "deck.pptx").name[:200]
        if not name.lower().endswith(".pptx"):
            raise schema.BadRequest("Upload a .pptx file. Older .ppt files must be saved as .pptx first.")
        try:
            text_info = self.extract(name, data)  # text for the storyline context
        except ExtractError:
            text_info = {"text": "", "chars": 0, "truncated": False}  # e.g. a deck made only of pictures
        result = {"name": name, "text": text_info["text"], "chars": text_info["chars"],
                  "truncated": text_info["truncated"], "deck_id": None, "slides": [], "transform": deck_ops is not None}
        if deck_ops is not None:
            try:
                inv = deck_ops.inventory(data)
            except DeckError as e:
                raise schema.BadRequest(str(e)) from e
            result["slides"] = inv["slides"]
            result["deck_id"] = self.work.put(data, name)
        self.audit("deck_upload", None, slides=len(result["slides"]))
        return result

    def deck_transform(self, payload):
        if deck_ops is None:
            raise schema.BadRequest("Deck transformation needs python-pptx on the server. See README: Offline install.")
        b = schema.brief(payload.get("brief"))
        try:
            data, name = self.work.get(str(payload.get("deck_id") or ""))
        except KeyError as e:
            raise schema.BadRequest("That deck is no longer on the server (uploads are kept for a limited time). Upload it again.") from e
        selected = sorted({int(i) for i in (payload.get("selected") or []) if str(i).isdigit()})
        if not selected:
            raise schema.BadRequest("Select at least one slide.")
        act = payload.get("actions") if isinstance(payload.get("actions"), dict) else {}
        actions = {"headlines": bool(act.get("headlines")), "simplify": bool(act.get("simplify")),
                   "retemplate": bool(act.get("retemplate"))}
        if not any(actions.values()):
            raise schema.BadRequest("Choose at least one change to make.")

        texts = deck_ops.slide_texts(data, set(selected))
        changes, meta_ai = {}, {"source": "none"}
        if actions["headlines"] or actions["simplify"]:
            changes, meta_ai = self._rewrite_slides(texts, actions, b)

        stem = Path(name).stem
        try:
            if actions["retemplate"]:
                tpl, meta, upload = self._meta(b, stem)
                template_bytes, template_is_potx = upload if upload else (None, False)
                out, report = deck_ops.retemplate(data, set(selected), changes, tpl, meta, slide_engine.template_path(tpl),
                                                   template_bytes, template_is_potx)
                out_name = _filename(stem + " " + tpl["name"], "pptx")
            else:
                out, report = deck_ops.apply_in_place(data, changes)
                out_name = _filename(stem + " revised", "pptx")
        except DeckError as e:
            raise schema.BadRequest(str(e)) from e
        before = {t["index"]: t["title"] for t in texts}
        for r in report:
            r["before"] = before.get(r["index"], "")
            r["after"] = (changes.get(r["index"]) or {}).get("title") or r["before"]
            r["warnings"] = (changes.get(r["index"]) or {}).get("warnings", []) + r["warnings"]
        fid = self.work.put(out, out_name)
        self.audit("deck_transform", b, slides=len(selected), source=meta_ai.get("source"), **actions)
        return dict(meta_ai, file_id=fid, filename=out_name, report=report,
                    note="The new deck contains only the selected slides." if actions["retemplate"] else
                    "All slides are kept; only the selected slides were changed.")

    def _rewrite_slides(self, texts, actions, b):
        """Ask the LLM for new titles/body text, in batches. Returns ({index: {title, body, warnings}}, meta).
        Every rewrite must keep the original's numbers and names and contain no placeholder text; a slide
        that fails is re-asked once with the exact problem, then left as it was (with a warning)."""
        by_index = {t["index"]: t for t in texts}

        def parse(data, valid):
            got = {}
            for item in data.get("slides") or []:
                if not isinstance(item, dict):
                    continue
                try:
                    idx = int(item.get("index"))
                except (TypeError, ValueError):
                    continue
                if idx not in valid:
                    continue
                body = item.get("body") if actions["simplify"] and isinstance(item.get("body"), list) else None
                got[idx] = {"title": str(item.get("title") or "").strip()[:300] if actions["headlines"] else "",
                            "body": [str(x).strip()[:400] for x in body if str(x).strip()] if body else None}
            return got

        def call():
            out = {}
            for start in range(0, len(texts), 8):
                batch = texts[start:start + 8]
                valid = {t["index"] for t in batch}
                system, user = prompts.transform(batch, actions, b)
                got = parse(self.llm.chat_json(system, user), valid)
                problems = {i: rewrite_problem(by_index[i], got[i]) for i in got}
                problems = {i: p for i, p in problems.items() if p}
                problems.update({i: "you returned nothing for this slide" for i in valid - set(got)})
                if problems:
                    retry = [by_index[i] for i in sorted(problems)]
                    system, user = prompts.transform(retry, actions, b, feedback=problems)
                    try:
                        again = parse(self.llm.chat_json(system, user), set(problems))
                    except Exception:  # noqa: BLE001  (a failed retry must not discard the good slides)
                        log.exception("deck_rewrite retry failed")
                        again = {}
                    for i in list(problems):
                        if i in again and not rewrite_problem(by_index[i], again[i]):
                            got[i] = again[i]
                            del problems[i]
                for i in valid:
                    if i in problems:
                        out[i] = {"title": "", "body": None,
                                  "warnings": ["Left unchanged: the rewrite %s" % problems[i]]}
                    else:
                        out[i] = got[i]
            if not out:
                raise ValueError("no slides returned")
            return out

        def rules():
            out = {}
            for t in texts:
                out[t["index"]] = {"title": fallback.sharpen(t["title"]) if actions["headlines"] and t["title"] else "",
                                   "body": None,
                                   "warnings": ["Main text kept as it is: simplifying needs the AI service"]
                                   if actions["simplify"] and len(t["body"]) > 5 else []}
            return out

        return self._ai("deck_rewrite", call, rules, b)

    def download(self, fid):
        try:
            data, name = self.work.get(fid)
        except KeyError as e:
            if not self.work.is_id(fid):
                raise schema.BadRequest("File not found. Check the download link.") from e
            raise schema.BadRequest("That file is no longer on the server (files are kept for %g hours). Run the transformation again."
                                    % self.cfg.get("work_retention_hours", 24)) from e
        return name, data

    def export_briefing(self, payload):
        b = schema.brief(payload.get("brief"))
        slides = schema.slides(payload.get("slides"))
        if not slides:
            raise schema.BadRequest("There are no slides to export.")
        title = str(payload.get("title") or b["topic"] or "Presentation")[:200]
        inc = payload.get("include") if isinstance(payload.get("include"), dict) else {}
        out = ["# " + title, "",
               "_%s · %s_" % (catalog.AUDIENCE_BY_ID[b["audience"]]["label"],
                              _dt.date.today().strftime("%d %B %Y")), ""]
        if inc.get("brief"):
            def call():
                system, user = prompts.briefing(b, title, slides)
                text = str(self.llm.chat_json(system, user)["brief"]).strip()
                if not text:
                    raise ValueError("empty brief")
                return text
            text, _meta = self._ai("briefing", call, lambda: fallback.briefing(b, title, slides), b)
            out += ["# Executive brief", "", text, ""]
        if inc.get("notes"):
            out += ["# Speaker notes", ""]
            for i, s in enumerate(slides, 1):
                out += ["## %d. %s" % (i, s["headline"]), "", s["notes"] or "_No notes yet._", ""]
        if inc.get("qa"):
            qs = payload.get("qa") if isinstance(payload.get("qa"), list) else []
            if qs:
                out += ["# Anticipated questions", ""]
                for q in qs[:10]:
                    if isinstance(q, dict):
                        out += ["**Q: %s**" % q.get("question", ""), "", str(q.get("answer", "")), "",
                                "_Evidence: %s_" % q.get("evidence", "–"), ""]
        self.audit("export_briefing", b, slides=len(slides))
        return _filename(title + " briefing", "md"), "\n".join(out).encode("utf-8")


def _filename(title, ext):
    slug = re.sub(r"[^\w\- ]+", "", title, flags=re.UNICODE).strip().replace(" ", "_")[:80] or "presentation"
    return "%s_%s.%s" % (slug, _dt.date.today().isoformat(), ext)


_WEEKEND = {4, 5}  # Friday, Saturday: the Saudi Arabia working week is Sunday-Thursday.


def _business_days_before(submission, meeting):
    """Business days strictly between two ISO dates, or None if either is missing/invalid."""
    try:
        s, m = _dt.date.fromisoformat(submission), _dt.date.fromisoformat(meeting)
    except (ValueError, TypeError):
        return None
    if m < s:
        return None  # schema.board_context rejects this before it gets here
    days, d = 0, s
    while d < m:
        d += _dt.timedelta(days=1)
        if d.weekday() not in _WEEKEND:
            days += 1
    return days


def _enforce_decision_slide(result, slides):
    """PRES-08 is judged on what the board will see. The model also reads the brief, and has passed
    PRES-08 by quoting a decision that is on no slide (test report D-02), so a deck without a decision
    slide always fails it, and its Decision clarity score is capped to match Quality check."""
    if any(s.get("kind") == "decision" for s in slides):
        return
    for c in result["compliance"]:
        if c["id"] == "PRES-08" and c["result"] != "FAIL":
            c.update(result="FAIL", evidence="No slide states the action sought from GEC/GIC; the decision appears only in the brief.",
                     action="Add a closing decision slide that restates the ask.")
    for d in result["board_readiness"]:
        if d["id"] == "decision_clarity" and d["score"] is not None and d["score"] > 2:
            d.update(score=2, comment="No slide states the decision the board is asked to take.")


def _sub01(ctx):
    """SUB-01's business-day lead time is arithmetic, not judgement: computed here rather than
    asked of the LLM (or approximated by the fallback), and always inserted into the result."""
    rule = catalog.BOARD_RULES_BY_ID["SUB-01"]
    n = _business_days_before(ctx.get("submission_date"), ctx.get("meeting_date"))
    if n is None:
        result, evidence, action = "NOT VERIFIABLE", "Submission date and/or meeting date was not provided.", "Supply both dates to check this automatically."
    elif n >= 6:
        result, evidence, action = "PASS", "%d business day%s between submission and the meeting." % (n, "" if n == 1 else "s"), ""
    else:
        result, evidence, action = "FAIL", "Only %d business day%s between submission and the meeting; 6 or more are required." % (n, "" if n == 1 else "s"), \
            "Submit at least 6 business days before the meeting date."
    return {"id": "SUB-01", "category": rule["category"], "requirement": rule["requirement"], "critical": False,
            "result": result, "evidence": evidence, "action": action}
