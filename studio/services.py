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
            meta = {"source": "rules", "warning": "The AI service was unavailable (%s). Built-in rules were used instead." % str(e).rstrip(".")}
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
            data["slides"] = data["slides"][:max(hi, 1)]
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
            system, user = prompts.sharpen(headline, body, b)
            h = str(self.llm.chat_json(system, user, max_tokens=300)["headline"]).strip()
            if not h:
                raise ValueError("empty headline")
            return {"headline": h[:300]}

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
        tpl = catalog.template(b["template"])
        return tpl, {"template_name": tpl["name"], "title": title,
                     "audience": catalog.AUDIENCE_BY_ID[b["audience"]]["label"],
                     "date": _dt.date.today().strftime("%d %B %Y")}

    def export_pptx(self, payload):
        b = schema.brief(payload.get("brief"))
        slides = schema.slides(payload.get("slides"))
        if not slides:
            raise schema.BadRequest("There are no slides to export.")
        title = str(payload.get("title") or b["topic"] or "Presentation")[:200]
        tpl, meta = self._meta(b, title)
        data = slide_engine.build(title, slides, meta, tpl)
        self.audit("export_pptx", b, slides=len(slides), engine=slide_engine.ENGINE)
        return _filename(title, "pptx"), data

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
                tpl, meta = self._meta(b, stem)
                out, report = deck_ops.retemplate(data, set(selected), changes, tpl, meta, slide_engine.template_path(tpl))
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
        fid = self.work.put(out, out_name)
        self.audit("deck_transform", b, slides=len(selected), source=meta_ai.get("source"), **actions)
        return dict(meta_ai, file_id=fid, filename=out_name, report=report,
                    note="The new deck contains only the selected slides." if actions["retemplate"] else
                    "All slides are kept; only the selected slides were changed.")

    def _rewrite_slides(self, texts, actions, b):
        """Ask the LLM for new titles/body text, in batches. Returns ({index: {title, body}}, meta)."""
        def call():
            out = {}
            for start in range(0, len(texts), 8):
                batch = texts[start:start + 8]
                system, user = prompts.transform(batch, actions, b)
                data = self.llm.chat_json(system, user)
                valid = {t["index"] for t in batch}
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
                    out[idx] = {"title": str(item.get("title") or "")[:300] if actions["headlines"] else "",
                                "body": [str(x)[:300] for x in body if str(x).strip()][:6] if body else None}
            if not out:
                raise ValueError("no slides returned")
            return out

        def rules():
            out = {}
            for t in texts:
                out[t["index"]] = {"title": fallback.sharpen(t["title"]) if actions["headlines"] and t["title"] else "",
                                   "body": t["body"][:5] if actions["simplify"] and len(t["body"]) > 5 else None}
            return out

        return self._ai("deck_rewrite", call, rules, b)

    def download(self, fid):
        try:
            data, name = self.work.get(fid)
        except KeyError as e:
            raise schema.BadRequest("That file has expired. Run the transformation again.") from e
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
