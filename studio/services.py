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

from . import __version__, catalog, fallback, prompts, review, schema
from . import slides as slide_engine
from .checks import (MAX_HEADLINE_WORDS, POLITICAL_RISK, clean_storyline, flag_invented, headline_problem,
                     invented_figures, missing_facts, numbers, rewrite_problem, slides_stating_ask)
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
        """Key facts in full, then the uploaded files within max_context_chars. The budget is shared: each
        file gets an equal share, and what a small file does not use goes to the larger ones. Cutting the
        joined text at the limit instead dropped every file after a long one (the demo case: a 63,000-
        character PDF left no room for the company's own workbook, uploaded second)."""
        facts = ("### Key facts provided by the presenter\n" + brief["facts"]) if brief.get("facts") else ""
        limit = int(self.cfg["max_context_chars"])
        files = [f for f in re.split(r"(?m)^(?=### )", uploaded or "") if f.strip()]
        budget = max(0, limit - len(facts))
        shares, left = {}, budget
        for k, i in enumerate(sorted(range(len(files)), key=lambda i: len(files[i]))):
            shares[i] = min(len(files[i]), left // (len(files) - k))
            left -= shares[i]
        kept = [f if shares[i] >= len(f) else f[:shares[i]].rstrip() + "\n[...rest of this file omitted for length]"
                for i, f in enumerate(files) if shares[i] > 0]
        return "\n\n".join(x for x in [facts] + [k.strip() for k in kept] if x)

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
        return {"status": "ok", "version": __version__, "llm": self.llm.health(),
                "pptx": dict(slide_engine.status(), transform=deck_ops is not None), "pdf": PDF_SUPPORTED}

    def storyline(self, payload):
        b = schema.brief(payload.get("brief"))
        if not b["topic"]:
            raise schema.BadRequest("Add a presentation topic.")
        version = payload.get("version") if payload.get("version") in schema.VERSIONS else "full"
        ctx = self._context(b, str(payload.get("context") or ""))
        lo, hi = catalog.slide_range(b["length"], version, b["task"])

        source_figures = numbers(" ".join([b["topic"], b["decision"], ctx]))

        def call():
            system, user = prompts.storyline(b, version, ctx)
            data = schema.storyline(self.llm.chat_json(system, user), b["topic"])
            invented = invented_figures(data["slides"], source_figures)
            if invented:
                # every figure must come from the brief (round 6: an invented plan when the brief had no facts)
                system, user = prompts.storyline(b, version, ctx, invented=invented)
                data = schema.storyline(self.llm.chat_json(system, user), b["topic"])
            data["slides"] = clean_storyline(data["slides"][:max(hi, 1)], bool(ctx))
            if len(data["slides"]) < lo:
                # e.g. one "please send me facts" slide when no facts were given (test report D-09)
                raise ValueError("the AI returned %d slide%s, fewer than the %d asked for"
                                 % (len(data["slides"]), "" if len(data["slides"]) == 1 else "s", lo))
            self._shorten_headlines(data["slides"], b)
            flag_invented(data["slides"], source_figures)
            return data

        result, meta = self._ai("storyline", call, lambda: fallback.storyline(b, version), b)
        result.update(meta)
        result["version"] = version
        return result

    def _shorten_headlines(self, slides, b, limit=3):
        """Headlines over the word limit get one targeted retry each (at most `limit` per deck, so a bad
        answer can't multiply the wait); a retry that still fails leaves the original for Quality check
        to flag."""
        # cover slides included: Quality check holds every headline to the limit
        long_ones = [s for s in slides if len(s["headline"].split()) > MAX_HEADLINE_WORDS][:limit]
        for s in long_ones:
            try:
                system, user = prompts.sharpen(s["headline"], s["body"], b, (s["headline"], headline_problem(s["headline"])))
                h = str(self.llm.chat_json(system, user, max_tokens=300)["headline"]).strip()
            except (LLMError, ValueError, KeyError, TypeError) as e:
                log.warning("storyline: could not shorten a headline (%s)", e)
                continue
            if h and not headline_problem(h) and not missing_facts([s["headline"]], [h] + s["body"]):
                s["headline"] = h[:300]

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
        _enforce_decision_slide(result, slides, b["decision"])
        _enforce_opening_ask(result, slides, b["decision"])
        _apply_context(result, slides, ctx)
        result["compliance"].insert(0, _sub01(ctx))
        result["readiness"] = _readiness(result)
        result["summary"] = _settle_summary(result)
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
            # held to Quality check's own rules: up to two retries with the reason, then the built-in rules
            # (one retry still fell back about one run in four: the model overshoots to 16-18 words)
            rejected = None
            for _attempt in range(3):
                system, user = prompts.sharpen(headline, body, b, rejected)
                h = str(self.llm.chat_json(system, user, max_tokens=300)["headline"]).strip()
                problem = headline_problem(h)
                if not problem:
                    return {"headline": h[:300]}
                rejected = (h, problem)
            raise ValueError("sharpened headline still fails: " + rejected[1])

        result, meta = self._ai("sharpen", call, lambda: {"headline": fallback.sharpen(headline)})
        result.update(meta)
        # lets the UI tell "already an action title" apart from "couldn't rewrite it" (test report R-03)
        result["meets_rules"] = not headline_problem(result["headline"])
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

        texts = deck_ops.slide_texts(data, set(selected), whole_slide=actions["retemplate"])
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
            # say so when a headline asked for is still a topic label, rather than leave it silently (S-02)
            src = next((t for t in texts if t["index"] == r["index"]), {})
            if (actions["headlines"] and not src.get("cover") and r["after"] == r["before"] and r["before"]
                    and headline_problem(r["before"]) and not any(w.startswith("Left unchanged") for w in r["warnings"])):
                r["warnings"].append("Headline not rewritten: the slide gave no finding to state. Write one yourself.")
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
                boxes = bool(by_index[idx].get("boxes"))
                if len(by_index[idx]["body"]) <= 2 and not boxes:
                    body = None  # one or two lines (a KPI tile, a caption): nothing to simplify
                got[idx] = {"title": str(item.get("title") or "").strip()[:300] if actions["headlines"] else "",
                            "body": [str(x).strip()[:400] for x in body] if body else None, "boxes": boxes}
                if got[idx]["body"] is not None and not boxes:
                    got[idx]["body"] = [x for x in got[idx]["body"] if x]
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


READINESS_CAP_ON_CRITICAL = 2.5


def _readiness(result):
    """The overall board-readiness score: the mean of the scored dimensions, capped while any critical
    checklist item fails. A deck that fails a critical check is not board-ready, however polished
    (test report R-02: 4.4/5 with PRES-08 failing)."""
    scores = [d["score"] for d in result["board_readiness"] if d["score"] is not None]
    raw = round(sum(scores) / len(scores), 1) if scores else None
    critical = [c["id"] for c in result["compliance"] if c.get("critical") and c["result"] == "FAIL"]
    capped = raw is not None and bool(critical) and raw > READINESS_CAP_ON_CRITICAL
    return {"score": READINESS_CAP_ON_CRITICAL if capped else raw, "raw_score": raw, "capped": capped,
            "board_ready": not critical, "critical_fails": critical}


# any sentence about readiness: the verdict sentence now owns that topic
_READY_CLAIM = re.compile(r"\b(ready|readiness|well prepared|strong on|strong overall)\b", re.I)
# a sentence claiming a critical failure, on a deck where none fails
_CRITICAL_CLAIM = re.compile(r"\bcritical\b", re.I)
# praise words; "well" only as "well sourced" / "well-structured", so "thin as well" is not praise
_PRAISE = re.compile(r"\b(strong|clear|good|excellent|solid|effective|compelling|robust|high|well[- ]\w+ed)\b", re.I)
_NEGATED = re.compile(r"\b(not|no|never|hardly|lacks?|lacking)\s+(?:\w+\s+)?$", re.I)


def _praises(sentence):
    """True when the sentence praises something: a praise word not negated just before it ("not strong")."""
    return any(not _NEGATED.search(sentence[:m.start()]) for m in _PRAISE.finditer(sentence))


def _lower_first(text):
    """"Presentation includes…" -> "presentation includes…", but "OOK investments…" stays as it is."""
    return text[:1].lower() + text[1:] if text[1:2].islower() else text


def _settle_summary(result):
    """The summary as the final word, written after the critical checks and the cap. The model writes its
    summary before PRES-08 is enforced and the score capped, so it can call a failing deck "highly ready"
    (test report S-01). When a critical check fails, the summary opens with that verdict, and model
    sentences claiming readiness, or praising a dimension that was capped, are dropped."""
    rd = result["readiness"]
    summary = result.get("summary") or ""
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", summary) if x.strip()]
    if rd["board_ready"]:
        # the model also misreads non-critical checks as critical and calls a passing deck "not
        # board-ready because it fails the critical PRES-07" (round 7); the verdict comes from the checks
        open_items = [c for c in result["compliance"] if not c.get("critical") and c["result"] in ("FAIL", "WARNING")]
        verdict = "Board-ready: no critical check fails."
        if open_items:
            verdict += " Still to fix: %s." % "; ".join("%s (%s)" % (c["id"], _lower_first(c["requirement"]).rstrip("."))
                                                       for c in open_items[:4])
        keep = [x for x in sentences if not _READY_CLAIM.search(x) and not _CRITICAL_CLAIM.search(x)]
        result["verdict"], result["summary_detail"] = verdict, " ".join(keep)
        return " ".join([verdict] + keep)
    failing = [c for c in result["compliance"] if c["id"] in rd["critical_fails"]]
    capped_dims = [d["label"].lower() for d in result["board_readiness"] if d["score"] is not None and d["score"] <= 3]
    # drop praise of a dimension that scored 3 or less, but keep criticism of it ("Evidence is thin"); a
    # sentence that praises it in passing ("clear, though the timeline could be tighter") still goes
    keep = [x for x in sentences if not _READY_CLAIM.search(x)
            and not (any(dim in x.lower() for dim in capped_dims) and _praises(x))]
    verdict = "Not board-ready: critical check%s %s fail%s (%s)." % (
        "s" if len(failing) > 1 else "", ", ".join(c["id"] for c in failing), "" if len(failing) > 1 else "s",
        "; ".join(c["requirement"].rstrip(".") for c in failing))
    if rd["capped"]:
        verdict += " Readiness is capped at %g/5 until %s fixed." % (rd["score"], "they are" if len(failing) > 1 else "it is")
    # the page shows the verdict in its banner, so it also gets the two halves (no verdict twice in a row)
    result["verdict"], result["summary_detail"] = verdict, " ".join(keep)
    return " ".join([verdict] + keep)


def _apply_context(result, slides, ctx):
    """Which checklist items apply follows from the context the user chose, not from the model's reading of
    the deck (round 8 W-01: with OOK = Yes, PRES-09 came back "Not applicable" while its own evidence said
    the Political Risk Framework was missing; with CMS chosen, COMP-07 said "not a capital program item").
    - OOK yes: PRES-09 is PASS when the slides carry Political Risk Framework content, otherwise FAIL;
      COMP-09 is NOT VERIFIABLE (a consultation). OOK no: both NOT APPLICABLE.
    - Presentation type: COMP-07 (CMS gates) applies to CMS, COMP-08 (transaction gates) to transactions;
      the other is NOT APPLICABLE. Gate requirements are paperwork, so an applicable item is NOT VERIFIABLE,
      and its wording names the stage gate chosen."""
    by_id = {c["id"]: c for c in result["compliance"]}
    text = " ".join(" ".join([s.get("headline", "")] + list(s.get("body") or [])) for s in slides)
    ook, ptype, gate = ctx.get("ook_investment"), ctx.get("presentation_type"), ctx.get("stage_gate")
    gate_name = catalog.STAGE_GATES.get(gate, "") if gate and gate != "na" else ""

    def put(cid, result_, evidence, action=""):
        if cid in by_id:
            by_id[cid].update(result=result_, evidence=evidence, action=action)

    if ook == "yes":
        found = [i for i, s in enumerate(slides, 1)
                 if POLITICAL_RISK.search(" ".join([s.get("headline", "")] + list(s.get("body") or [])))]
        if found:
            put("PRES-09", "PASS", "OOK investment: Political Risk Framework content on slide%s %s."
                % ("s" if len(found) > 1 else "", ", ".join(map(str, found))))
        else:
            put("PRES-09", "FAIL", "OOK investment, but no slide presents the Political Risk Framework.",
                "Add the Political Risk Framework assessment for the host country.")
        put("COMP-09", "NOT VERIFIABLE", "OOK investment: the Investment Guidelines Group consultation cannot be confirmed from the deck.",
            "Confirm the consultation on the political framework separately.")
    elif ook == "no":
        put("PRES-09", "NOT APPLICABLE", "Not an OOK investment (set in the context).")
        put("COMP-09", "NOT APPLICABLE", "Not an OOK investment (set in the context).")

    gate_txt = (" for %s" % gate_name) if gate_name else ""
    if ptype == "cms":
        put("COMP-07", "NOT VERIFIABLE", "CMS item: the CMS gate requirements%s cannot be confirmed from the deck." % gate_txt,
            "Confirm the CMS gate%s package separately." % gate_txt)
        put("COMP-08", "NOT APPLICABLE", "Not a transaction item (CMS selected in the context).")
    elif ptype == "transaction":
        put("COMP-08", "NOT VERIFIABLE", "Transaction item: NBD consultation and GI-30.001 gate requirements%s cannot be "
            "confirmed from the deck." % gate_txt, "Confirm the NBD consultation and gate%s requirements separately." % gate_txt)
        put("COMP-07", "NOT APPLICABLE", "Not a Capital Program item (transaction selected in the context).")
    elif ptype == "other":
        put("COMP-07", "NOT APPLICABLE", "Not a Capital Program item (Other selected in the context).")
        put("COMP-08", "NOT APPLICABLE", "Not a transaction item (Other selected in the context).")


def _enforce_opening_ask(result, slides, decision):
    """PRES-03 decided from the same "which slides state the ask" as PRES-08. The model failed it about one
    run in ten on a deck whose first slide plainly states the ask (round 6/7), and the rule is mechanical:
    the cover or the first content slide states the action required, or it does not."""
    content = [i for i, s in enumerate(slides, 1) if s.get("kind") != "title"]
    opening = {1} | set(content[:1])
    stated = [i for i in slides_stating_ask(slides, decision) if i in opening]
    for c in result["compliance"]:
        if c["id"] != "PRES-03":
            continue
        if stated and c["result"] != "PASS":
            c.update(result="PASS", evidence="Slide %d states the action required from GEC/GIC." % stated[0], action="")
        elif not stated and c["result"] == "PASS" and (decision or "").strip():  # no decision: the model judges
            c.update(result="FAIL", evidence="Neither the cover nor the first content slide states the action required.",
                     action="Open with the decision you need from GEC/GIC.")


def _enforce_decision_slide(result, slides, decision):
    """PRES-08 is judged on what the board will see. The model also reads the brief, and has passed
    PRES-08 by quoting a decision that is on no slide (test report D-02), so a deck without a decision
    slide always fails it, and its Decision clarity score is capped to match Quality check. The wording
    says where the ask does appear, so it never contradicts a PRES-03 pass that quotes it (N-04)."""
    if any(s.get("kind") == "decision" for s in slides):
        return
    stated = slides_stating_ask(slides, decision)
    content = [s for s in slides if s.get("kind") != "title"]
    last = content[-1]["kind"] if content else "title"
    if stated:
        where = "slide%s %s" % ("s" if len(stated) > 1 else "", ", ".join(map(str, stated)))
        evidence = "The ask is stated on %s, but the deck does not close on it: the final slide is a %s slide." % (where, last)
        score, comment = 3, "The ask is on %s but is not restated at the close." % where
    else:
        evidence = "No slide states the action sought from GEC/GIC; the decision appears only in the brief."
        score, comment = 2, "No slide states the decision the board is asked to take."
    for c in result["compliance"]:
        if c["id"] == "PRES-08" and c["result"] != "FAIL":
            c.update(result="FAIL", evidence=evidence, action="Add a closing decision slide that restates the ask.")
    for d in result["board_readiness"]:
        if d["id"] == "decision_clarity" and d["score"] is not None and d["score"] > score:
            d.update(score=score, comment=comment)


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
