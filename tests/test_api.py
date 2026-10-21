"""End-to-end API tests with a mock LLM. Standard library only.

    python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import mock_llm  # noqa: E402

BRIEF = {"task": "new", "topic": "Q3 business performance review", "decision": "Approve a 3% mid-market price increase",
         "facts": "Revenue +4% vs plan. Gross margin -1.8 pts.", "audience": "board", "length": "mid",
         "source": "docs", "template": "corporate"}


def _start(server):
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


class Base(unittest.TestCase):
    llm_up = True

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls.mock = _start(mock_llm.serve(0)) if cls.llm_up else None
        llm_url = "http://127.0.0.1:%d/v1" % cls.mock.server_address[1] if cls.mock else "http://127.0.0.1:9/v1"
        os.environ["STUDIO_LLM_BASE_URL"] = llm_url
        os.environ["STUDIO_LLM_TIMEOUT"] = "5"
        os.environ["STUDIO_AUDIT_LOG"] = str(ROOT / "logs" / "test-audit.log")
        os.environ["STUDIO_SERVER_LOG"] = ""
        os.environ["STUDIO_WORK_DIR"] = str(ROOT / "work" / "test")
        import server as srv
        from studio import config
        from studio.services import Studio
        srv.Handler.studio = Studio(config.load())
        cls.app = _start(ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler))
        cls.base = "http://127.0.0.1:%d" % cls.app.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.app.server_close()
        if cls.mock:
            cls.mock.shutdown()
            cls.mock.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as r:
            return r.status, r.headers, r.read()

    def post(self, path, obj=None, raw=None, headers=None):
        data = raw if raw is not None else json.dumps(obj or {}).encode()
        req = urllib.request.Request(self.base + path, data=data, method="POST",
                                     headers=headers or {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()


class WithLLM(Base):
    llm_up = True

    def test_static_and_security_headers(self):
        st, h, body = self.get("/")
        self.assertEqual(st, 200)
        self.assertIn(b"Executive Presentation Studio", body)
        self.assertIn("default-src 'self'", h["Content-Security-Policy"])
        for p in ("/static/js/app.js", "/static/js/api.js", "/static/js/thumbs.js", "/static/css/app.css", "/static/img/icon.svg"):
            self.assertEqual(self.get(p)[0], 200, p)

    def test_path_traversal_blocked(self):
        try:
            st = self.get("/static/../server.py")[0]
        except urllib.error.HTTPError as e:
            st = e.code
        self.assertEqual(st, 404)

    def test_meta_health(self):
        meta = json.loads(self.get("/api/meta")[2])
        self.assertTrue(meta["templates"] and meta["audiences"])
        health = json.loads(self.get("/api/health")[2])
        self.assertTrue(health["llm"]["reachable"])
        self.assertIn("engine", health["pptx"])

    def test_storyline_review_qa(self):
        st, _, body = self.post("/api/storyline", {"brief": BRIEF, "version": "full", "context": ""})
        self.assertEqual(st, 200, body)
        s = json.loads(body)
        self.assertEqual(s["source"], "llm")
        self.assertGreaterEqual(len(s["slides"]), 3)
        st, _, body = self.post("/api/review", {"brief": BRIEF, "slides": s["slides"]})
        r = json.loads(body)
        self.assertTrue(any(not c["ok"] for c in r["checks"]))  # slide 3 has a placeholder + missing evidence
        st, _, body = self.post("/api/qa", {"brief": BRIEF, "slides": s["slides"]})
        self.assertEqual(json.loads(body)["source"], "llm")

    def test_advise_and_sharpen(self):
        a = json.loads(self.post("/api/advise", {"message": "why did turnover increase"})[2])
        self.assertEqual(a["primary"]["kind"], "driver")
        h = json.loads(self.post("/api/sharpen", {"headline": "Margin overview", "body": []})[2])
        self.assertIn("1.8", h["headline"])

    def test_export_pptx_valid(self):
        s = json.loads(self.post("/api/storyline", {"brief": BRIEF, "version": "full"})[2])
        st, h, body = self.post("/api/export/pptx", {"brief": BRIEF, "title": s["title"], "slides": s["slides"]})
        self.assertEqual(st, 200)
        self.assertIn("attachment", h["Content-Disposition"])
        zf = zipfile.ZipFile(io.BytesIO(body))
        names = zf.namelist()
        self.assertIn("ppt/presentation.xml", names)
        self.assertEqual(len([n for n in names if n.startswith("ppt/slides/slide")]), len(s["slides"]))
        import xml.etree.ElementTree as ET
        for n in names:
            if n.endswith(".xml") or n.endswith(".rels"):
                ET.fromstring(zf.read(n))  # every part is well-formed

    def test_briefing(self):
        s = json.loads(self.post("/api/storyline", {"brief": BRIEF})[2])
        st, _, body = self.post("/api/export/briefing", {"brief": BRIEF, "title": "T", "slides": s["slides"],
                                                         "include": {"brief": True, "notes": True, "qa": True},
                                                         "qa": [{"question": "Q?", "answer": "A", "evidence": "E"}]})
        text = body.decode()
        self.assertIn("# Executive brief", text)
        self.assertIn("# Speaker notes", text)
        self.assertIn("Q?", text)

    def test_extract_docx_and_errors(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml",
                        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                        "<w:p><w:r><w:t>Revenue grew 4%</w:t></w:r></w:p></w:body></w:document>")
        st, _, body = self.post("/api/extract", raw=buf.getvalue(),
                                headers={"Content-Type": "application/octet-stream", "X-Filename": "notes.docx"})
        self.assertEqual(st, 200, body)
        self.assertIn("Revenue grew 4%", json.loads(body)["text"])
        st, _, body = self.post("/api/extract", raw=b"%PDF-1.4 broken", headers={"X-Filename": "x.pdf"})
        self.assertEqual(st, 400)   # unreadable PDF, or PDF support not installed: both are a clear 400
        st, _, body = self.post("/api/extract", raw=b"x", headers={"X-Filename": "old.ppt"})
        self.assertIn("Older Office formats", json.loads(body)["error"])

    def test_bad_requests(self):
        self.assertEqual(self.post("/api/storyline", raw=b"not json")[0], 400)
        self.assertEqual(self.post("/api/storyline", {"brief": dict(BRIEF, topic="")})[0], 400)
        self.assertEqual(self.post("/api/nope", {})[0], 404)


try:
    import pptx  # noqa: F401
    import sample_deck
    HAVE_PPTX = True
except ImportError:
    HAVE_PPTX = False


@unittest.skipUnless(HAVE_PPTX, "python-pptx not installed")
class Decks(Base):
    llm_up = True

    def _upload(self):
        st, _, body = self.post("/api/deck/upload", raw=sample_deck.build(),
                                headers={"Content-Type": "application/octet-stream", "X-Filename": "ops%20review.pptx"})
        self.assertEqual(st, 200, body)
        return json.loads(body)

    def test_upload_inventory(self):
        d = self._upload()
        self.assertEqual(len(d["slides"]), 4)
        self.assertTrue(d["deck_id"])
        s3 = d["slides"][2]
        self.assertEqual((s3["charts"], s3["pictures"]), (1, 1))
        self.assertIn("handling time", d["text"])

    def _open(self, fid):
        from pptx import Presentation
        st, h, body = self.get("/api/download/" + fid)
        self.assertEqual(st, 200)
        self.assertIn("presentationml", h["Content-Type"])
        return Presentation(io.BytesIO(body))

    def test_transform_in_place(self):
        d = self._upload()
        st, _, body = self.post("/api/deck/transform", {"deck_id": d["deck_id"], "selected": [2],
                                "actions": {"headlines": True, "simplify": True}, "brief": BRIEF})
        self.assertEqual(st, 200, body)
        r = json.loads(body)
        self.assertEqual(r["source"], "llm")
        prs = self._open(r["file_id"])
        self.assertEqual(len(prs.slides), 4)                      # all slides kept
        self.assertTrue(prs.slides[1].shapes.title.text.endswith("the key finding"))
        self.assertEqual(prs.slides[0].shapes.title.text, "Quarterly operations review")  # unselected untouched
        body_tf = prs.slides[1].placeholders[1].text_frame
        self.assertEqual(len(body_tf.paragraphs), 3)

    def test_transform_retemplate_carries_visuals(self):
        d = self._upload()
        st, _, body = self.post("/api/deck/transform", {"deck_id": d["deck_id"], "selected": [1, 3, 4],
                                "actions": {"retemplate": True}, "brief": BRIEF})
        self.assertEqual(st, 200, body)
        r = json.loads(body)
        prs = self._open(r["file_id"])
        self.assertEqual(len(prs.slides), 3)
        kinds = [[sh.has_chart if hasattr(sh, "has_chart") else False for sh in s.shapes] for s in prs.slides]
        self.assertTrue(any(kinds[1]))                               # chart rebuilt natively
        self.assertTrue(any(getattr(sh, "has_table", False) and sh.has_table for sh in prs.slides[2].shapes))
        self.assertTrue(any("Picture carried over" in c for c in r["report"][1]["changes"]))

    def test_storyline_chart_export_is_native(self):
        from pptx import Presentation
        slides = [{"kind": "bars", "headline": "Revenue rose 8% on enterprise demand", "body": ["Enterprise +12%"],
                   "chart": {"type": "column", "categories": ["Q1", "Q2"], "series": [{"name": "Rev", "values": ["100", "108"]}]},
                   "evidence": {"status": "linked", "source": "Finance"}}]
        st, _, body = self.post("/api/export/pptx", {"brief": BRIEF, "title": "T", "slides": slides})
        self.assertEqual(st, 200)
        prs = Presentation(io.BytesIO(body))
        self.assertTrue(any(getattr(sh, "has_chart", False) and sh.has_chart for sh in prs.slides[0].shapes))
        self.assertIn("Finance", prs.slides[0].notes_slide.notes_text_frame.text)

    def test_expired_deck(self):
        st, _, body = self.post("/api/deck/transform", {"deck_id": "0" * 32, "selected": [1], "actions": {"headlines": True}, "brief": BRIEF})
        self.assertEqual(st, 400)
        self.assertIn("Upload it again", json.loads(body)["error"])


class WithoutLLM(Base):
    llm_up = False

    def test_fallback_deck_rewrite(self):
        if not HAVE_PPTX:
            self.skipTest("python-pptx not installed")
        st, _, body = self.post("/api/deck/upload", raw=sample_deck.build(), headers={"X-Filename": "d.pptx"})
        d = json.loads(body)
        r = json.loads(self.post("/api/deck/transform", {"deck_id": d["deck_id"], "selected": [2],
                                 "actions": {"headlines": True, "simplify": True}, "brief": BRIEF})[2])
        self.assertEqual(r["source"], "rules")
        self.assertEqual(r["report"][0]["after"], "Customer service")  # "Overview of" stripped by the rules

    def test_fallback_storyline(self):
        st, _, body = self.post("/api/storyline", {"brief": BRIEF, "version": "summary"})
        s = json.loads(body)
        self.assertEqual(s["source"], "rules")
        self.assertIn("warning", s)
        self.assertEqual(len(s["slides"]), 5)
        a = json.loads(self.post("/api/advise", {"message": "compare three vendors"})[2])
        self.assertEqual(a["primary"]["kind"], "matrix")


if __name__ == "__main__":
    unittest.main()
