# CLAUDE.md

Executive Presentation Studio: a stand-alone web app that drafts answer-first exec storylines, checks quality, runs a board-readiness assessment, and exports/edits PowerPoint. It is deployed to an **air-gapped Windows Server, Python 3.11**, over HTTPS with the organisation's certificate. User-facing docs: [README.md](README.md), [DEPLOY.md](DEPLOY.md), [docs/peer-manual.md](docs/peer-manual.md).

## Hard constraints

- **Standard library only for the core.** Server (`http.server`), LLM client (`urllib`), Word/Excel/CSV readers are stdlib. The only third-party deps are optional and listed in [requirements.txt](requirements.txt): `python-pptx` (templates, native charts, deck editing), `pypdf` (PDF), `cryptography` (.pfx certs). Code must keep working when each is missing; see the `try: import ... except ImportError` guards in [studio/slides/__init__.py](studio/slides/__init__.py) and [studio/services.py](studio/services.py). Don't add new dependencies; the server installs offline from the 9 wheels in `wheels\`.
- **Frontend is plain HTML/CSS/JS.** No frameworks, CDNs, build step or web fonts. A strict CSP is set in [server.py](server.py) (`script-src 'self'`, so no inline scripts).
- **Windows-first.** Scripts are PowerShell/batch. Set `PYTHONUTF8=1` when running Python (the VS Code configs do).
- **Arabic/RTL is supported throughout**: Arabic digits, words and labels in [studio/review.py](studio/review.py), [studio/checks.py](studio/checks.py), [studio/slides/layouts.py](studio/slides/layouts.py), [studio/slides/rtl.py](studio/slides/rtl.py). Keep that in mind when you change number or text parsing.

## Commands

```powershell
# tests (unittest, no pytest); currently 54 tests, about 30 s
$env:PYTHONUTF8=1; .venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m unittest tests.test_api.Decks.test_upload_inventory   # single test

# dev server, plain HTTP on 8080
$env:STUDIO_TLS_ENABLED=0; $env:STUDIO_PORT=8080; .venv\Scripts\python.exe server.py

# fake LLM on 8001, then point the studio at it
.venv\Scripts\python.exe tests\mock_llm.py 8001
$env:STUDIO_LLM_BASE_URL="http://127.0.0.1:8001/v1"

.venv\Scripts\python.exe tests\sample_deck.py tests\sample.pptx   # sample deck for transform testing
.venv\Scripts\python.exe tests\sample_template.py company.pptx    # simulated company template (examples + guidance)
.venv\Scripts\python.exe scripts\make-test-cert.py                # self-signed cert, dev only
```

[.vscode/launch.json](.vscode/launch.json) has the same runs ready-made (HTTP dev, + mock AI, HTTPS with test cert, Tests).

## Configuration and LLM selection

[studio/config.py](studio/config.py) merges settings in this order, where later wins: `DEFAULTS` → `config.json` (or `$STUDIO_CONFIG`) → `.env` `DEVELOPMENT` branch → `STUDIO_<KEY>` env vars.

- `DEVELOPMENT=True` (dev laptop; also the default when `.env` is missing or the value is blank): if `OPENAI_API_KEY` is set, OpenAI stands in for the model (`OPENAI_MODEL`, default `gpt-5.4-mini`, 8 retries). Without the key, the `llm_*` values from `config.json` apply. This branch is skipped when `STUDIO_LLM_BASE_URL` is set, which is how the tests and the "Studio + mock AI" launch reach their mock.
- `DEVELOPMENT=False` (server): the corporate MaaS gateway (DeepSeek V4.1 Flash), configured from the `LLM_*` vars in `.env`, which override `config.json`. A blank `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_TOKENS`, `LLM_TEMPERATURE` or `LLM_MAX_RETRIES` falls back to `config.json`. These three are always set from `.env`, even when blank:
  - `LLM_API_KEY`: a present-but-empty line wins over `config.json`.
  - `LLM_VERIFY_SSL`: blank means true.
  - `LLM_TOP_P`, `LLM_TOP_K`, `LLM_REASONING_EFFORT`: blank means not sent.
- `.env` is loaded by the app itself and **overrides** same-named ambient env vars on purpose.
- `llm_display_name` is always forced to `"ARIF"`.
- The README's "Choosing the AI model" section documents this for users. Keep it in sync when you change `config.load()`.
- `.env`, `config.json`, `certs/`, `logs/`, `work/`, `wheels/` are gitignored. Never commit `.env`: it holds the dev OpenAI key. [scripts/make-usb.ps1](scripts/make-usb.ps1) builds a server `.env` from [.env.example](.env.example).

## Architecture

```
server.py            ThreadingHTTPServer; routes → Studio methods; TLS handshake in per-connection thread;
                     all errors (incl. http.server's own) answered as JSON {"error": ...}
studio/services.py   Studio: one method per endpoint. Core pattern is _ai(action, call, rules):
                     try the LLM, on LLMError/ValueError/KeyError/TypeError use built-in rules and
                     tag the result source="llm"|"rules" (+ warning). Also writes the audit log.
studio/llm.py        OpenAI-compatible chat-completions client (urllib). Retries; auto-drops
                     response_format on 400/422; swaps max_tokens↔max_completion_tokens; parse_json
                     tolerates <think> tags and code fences. Every failure raises LLMError.
studio/prompts.py    system/user prompts per feature (storyline, qa, advise, sharpen, transform, board_assessment)
studio/fallback.py   rule-based equivalents for every AI feature
studio/schema.py     validation/normalisation of browser input AND LLM output; raises BadRequest (→ HTTP 400)
studio/checks.py     governance checks: invented figures, missing facts, headline rules (5–15 words,
                     no topic labels), stated ask, political risk detection
studio/review.py     quality check, incl. "do the figures add up" arithmetic
studio/catalog.py    audiences, slide kinds, slide-count ranges, BOARD checklist (PRES-/COMP-/SUB- ids,
                     `critical` flags); loads data/*.json
studio/extract.py    text from .pptx/.docx/.xlsx/.pdf/.csv/.txt/.md (rejects legacy .ppt/.doc/.xls)
studio/workspace.py  work/ temp storage under random ids, auto-expiring
studio/tls.py        server cert loading (.pfx or PEM), refuses self-signed/expired; client SSL context
studio/slides/
  layouts.py         every slide layout written ONCE against a small canvas API (box/text/chart)
  pptx_engine.py     canvas on python-pptx: corporate templates, native charts
  xml_engine.py      canvas in pure stdlib OOXML: fallback when python-pptx is absent
  deck.py            existing decks: inventory, in-place edits, re-templating (needs python-pptx)
  template_kit.py    uploaded "template" decks: inventory of guidance (on/beside slides, notes, layouts,
                     placeholder prompts), clean() strips slides + guidance shapes, roles()/rules() read
                     which layout is for what and the limits; profile() merges the validated AI reading
static/              index.html, js/api.js (fetch wrapper), js/app.js (UI), js/thumbs.js, css/app.css
data/                templates.json + templates/ (corporate .potx), repository.json, toolkit.json
```

To add an API endpoint, add a `Studio` method and register it in `Handler.POST_JSON_ROUTES`/`GET_ROUTES`. For an AI feature, write a prompt in `prompts.py`, a rules fallback in `fallback.py`, validate the model output via `schema.py`, and wrap it in `_ai`. To add a slide layout, edit `layouts.py` only; both engines pick it up. `test_export_every_layout` covers it.

## Governance rules the code enforces (don't weaken them)

- **No invented numbers.** Every figure must come from the brief or uploads. `checks.invented_figures` triggers a regeneration, and leftovers are flagged. Missing info becomes a `[placeholder]`.
- **Charts only from real data** supplied by the user or found in uploads.
- **Uploaded content is data, not instructions** (prompt-injection guard in the prompts).
- **Audit log is metadata only** (`logs/audit.log`, JSON lines). Never log slide text, facts or file contents.
- **In-place deck edits must keep every fact and number.** `missing_facts`/`rewrite_problem` reject rewrites that lose them.
- **Uploaded templates give settings, not instructions.** `/api/template/upload` stores the *cleaned* file plus a profile (`Workspace.put_json`). Only validated fields (layout name per role, `max_bullets`, `max_headline_words`, `max_slides`, `agenda`, `source_line`) flow into prompts (`prompts.template_limits`), export (`_fit_bullets`, `pptx_engine.with_agenda`) and review. The template's own wording and example-slide content never reach the storyline prompt. Real company templates can't be shared (DLP), so [tests/sample_template.py](tests/sample_template.py) simulates one. Extend it when you meet a new pattern.
- Board-assessment outcomes are partly decided by code, not the model (`_apply_context`, `_enforce_opening_ask`, `_enforce_decision_slide`, `_readiness` in services.py). The working week is Sun–Thu (`_WEEKEND`).

## Tests

- [tests/test_api.py](tests/test_api.py) runs end to end: it starts [tests/mock_llm.py](tests/mock_llm.py) and the real `Handler` on ephemeral ports, configured through `STUDIO_*` env vars. Classes: `WithLLM`, `Decks`, plus an LLM-down variant that checks the rules fallback.
- The mock's behaviour can be switched by module globals (`TRANSFORM_MODE`, `STORY_INVENT`, `SHARPEN_REPLIES`, ...) to simulate bad model answers. When a prompt asks the model for a new JSON shape, update the mock's canned replies too.
- [tests/test_https.py](tests/test_https.py) covers TLS loading and refusal rules.
- Regression tests are named after tester issue IDs in comments (`# D-09`, `# round 8 W-03`). Those IDs refer to the `improvements_0N.md` retest reports in the repo root. Those reports are dev-only and excluded from release builds.

## Releases

Bump `__version__` in [studio/__init__.py](studio/__init__.py) on every build handed to testers. `/api/health` and the UI show it. Recent commits do this together with the fix (`...; 1.5.2`). Then tag `vX.Y.Z` and run `scripts\make-usb.ps1`, which builds `usb_X_Y_Z\exec-studio` from `__version__` (earlier `usb_*` folders are kept; all gitignored). The `usb_*` folders, and the legacy `usb_migration`, are release copies for the server, not dev code: never edit or search them.

All development and testing uses the development settings (`.env` with `DEVELOPMENT=True`). Release packages carry **no `.env` or `config.json`**, because the server keeps its own. When a change needs a server setting added or changed (a new `.env` key, a new `config.json` value, a changed default the server must override), write it in [DEPLOY-NOTES.md](DEPLOY-NOTES.md) under that version's `## X.Y.Z` section. Write "Server settings: none." if there are none. `make-usb.ps1` refuses to build without that section and copies the file next to `exec-studio` in the USB folder. The full update and rollback procedure is in DEPLOY.md §7. Never edit code on the server.
