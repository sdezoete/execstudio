# Improvements 01: fixes from the 23 Oct 2026 test report

Source: *Executive Presentation Studio — Test Report* (23 Oct 2026, @Sam). 35 cases: 23 pass, 5 partial, 7 fail.
The core brief → storyline → export path works; **Improve an existing deck** must not ship until 1–3 are fixed.

Order of work: 1–3 (release blockers) → 4 (one change, broad effect) → 5–8 → low items → extras.

---

## Critical / High

### 1. D-01 Transform deletes slide content and writes junk (Critical)
- **Cause**
  - `studio/slides/deck.py` `find_body()` keeps only the single text shape with the most text. Decks that put each
    KPI/bullet in its own text box lose the rest; `retemplate()` copies only title + that one body + visuals.
  - "Simplify" caps the body at 5 (prompt, `prompts.transform`), 6 (parser, `services._rewrite_slides`) and 5
    (fallback). Model output is not validated, so junk such as "Evidence needed: Evidence needed" is written.
- **Fix**
  - Extract all text shapes; carry secondary text boxes over (or into notes, with a report warning).
  - Content-preservation check in `_rewrite_slides`: every number / percentage / amount / capitalised name in the
    original must survive; re-prompt once, then keep the slide's original text and warn.
  - Reject empty, placeholder-only or title-echo output.
  - Report "Main text simplified" only when the simplification passed the checks.
  - Show the change report with a Download button instead of auto-downloading.

### 2. D-02 Board assessment passes PRES-08 falsely (High)
- **Cause** `prompts.board_assessment` asks the model to compare against "the brief's stated decision"; the
  brief is in the prompt, so the model passes PRES-08 with no decision slide present.
- **Fix**
  - Prompt: the brief is context only, never evidence; PRES-08 must be shown on a slide.
  - Decide PRES-08 deterministically in code (like SUB-01): last content slide not a decision slide → FAIL.
  - Cap Decision clarity at 2/5 when there is no decision slide.

### 3. D-14 Export drops bullets past the layout limit; "Evidence needed: Evidence needed" footer (High)
- **Cause** `layouts.items(s, n)` slices to 4–8 bullets depending on layout, silently. `schema.slides` defaults the
  gap to "Evidence needed" and both engines prefix "Evidence needed: ".
- **Fix**
  - Overflow bullets go into the speaker notes ("Moved from the slide:"); export reports it.
  - Default gap empty; footer only for a real gap; label "Evidence gap: …".

## Medium

### 4. D-03 Double-click leaves buttons stuck on "Thinking…"
- **Fix** `busy()` in `static/js/app.js`: return early when already busy; set/clear `disabled`; never overwrite the
  saved label. Fixes Design, Advisor, Export and Transform.

### 5. D-04 Sharpen breaks the 15-word rule
- **Fix** Validate with a shared `headline_ok()` (same rule as Quality check); re-prompt once with the word count,
  then fall back to `fallback.sharpen()`.

### 6. D-05 Repository search is exact-substring only
- **Fix** Tokenise, drop stop words, light stemming, small synonym map; match each term over title, question,
  category, layout; rank by hits. "why did costs rise" must return results.

### 7. D-06 Arithmetic slip ("phantom gap")
- **Fix** Prompt: components must reconcile to totals; never call a remainder "not specified" when the parts already
  sum to the total. Quality check rule that flags parts not summing to a stated total.

### 8. D-07 No date validation in Board assessment
- **Fix** Meeting date before submission date → 400 "Meeting date is before submission date"; inline UI error.

## Low

### 9. D-08 Stale validation error
- Clear on input / success / new brief; `aria-invalid` + `aria-describedby`.

### 10. D-09 Weak no-facts output; internal label leak
- No facts → skeleton storyline with `[placeholders]`, not a refusal. Strip chatbot phrasing from notes.
  `evidence.source` must not name "source documents" when nothing was uploaded.

### 11. D-10 Button label wrong after reload
- One `syncTaskUi()` used on change and after `restore()`.

### 12. D-11 Remove has no confirm or undo
- "Undo" in the Removed toast for ~8 s.

### 13. D-12 Misleading API messages
- Unsupported-type message lists the real types (incl. `.pdf` when available).
- Download: "not found" for unknown ids vs "expired".

### 14. D-13 Narrow-screen overflow
- Wrap slide action buttons; nav rail becomes a horizontal bar below ~480 px; pipeline wraps.

## Extras

15. **Progress for long calls**: elapsed seconds beside the spinner; warn when an upload exceeds the context limit.
16. **One output-validation layer**: storyline, sharpen and transform results go through the same checks.
17. **Regression tests** (mock LLM) for each fix: transform keeps figures; PRES-08 fails without decision slide;
    7-bullet export keeps overflow; long sharpen re-prompted; meeting < submission → 400; search placeholder hits.
18. **`tests/test_https.py`**: 2 tests error (pre-existing; client-abort on TLS write). Investigate.

---

## Status

| # | Item | Status | Where / how verified |
|---|------|--------|----------------------|
| 1 | D-01 Transform content loss | done | `deck.py` (footer never the body; other text boxes carried; small print → notes), `checks.rewrite_problem` + one retry in `_rewrite_slides`; report shown before download. Tests: lossy rewrite rejected, KPI tiles kept, footer ignored |
| 2 | D-02 PRES-08 false pass | done | Prompt: brief is not evidence. `_enforce_decision_slide`: no decision slide → PRES-08 FAIL, Decision clarity ≤ 2. Test with an over-generous mock reviewer |
| 3 | D-14 Export truncation / footer | done | `layouts.items` records overflow → speaker notes; `X-Studio-Notice` header → toast; footer only for a real gap ("Evidence gap: …"). Test: 7 bullets, nothing lost |
| 4 | D-03 busy() | done | Disables the button, refuses re-entry; all callers bail out. JS syntax-checked; not browser-tested |
| 5 | D-04 Sharpen length | done | `checks.headline_problem` shared with Quality check; one retry with the reason, then built-in rules. Test |
| 6 | D-05 Search | done | Word-level, stop words, stemming, synonyms, ranked. Checked in Node against `repository.json`: "why did costs rise" → Margin bridge first, Business case included |
| 7 | D-06 Arithmetic | done | Prompt rule + Quality check "Figures add up" (parts > total; phantom "unexplained" remainder). Test |
| 8 | D-07 Date validation | done | `schema.board_context` → 400; inline check + `aria-invalid` in the UI; same-day = 0 days (FAIL). Test |
| 9 | D-08 Stale error | done | `briefError()` clears on input / success / new brief; `aria-invalid` + `aria-describedby`. Not browser-tested |
| 10 | D-09 No-facts output | done | Prompt label no longer "SOURCE DOCUMENTS"; no-facts skeleton rule; `checks.clean_storyline`; too few slides → rules skeleton. Test |
| 11 | D-10 Label after reload | done | `syncTaskUi()` on change, reload and reset. Not browser-tested |
| 12 | D-11 Undo remove | done | Undo button in the toast (8 s). Not browser-tested |
| 13 | D-12 API messages | done | Type list includes .pdf when available; "File not found" vs "no longer on the server". Test |
| 14 | D-13 Mobile layout | done (partly verified) | Slide-row wrapper fixed; pipeline 3×2 under 600 px; nav as 3 tabs under 480 px. Headless Edge screenshot at ~500 px: no horizontal scroll. ≤480 px rules need a check on a real phone |
| 15 | Progress | done | Live seconds counter in every loading message; large-upload notice; clearer "too long" note |
| 16 | One output-validation layer | done | `studio/checks.py` used by transform, sharpen, storyline and Quality check |
| 17 | Regression tests | done | `tests/test_api.py`: 18 → 25 tests, all passing |
| 18 | HTTPS tests | done | Cause: `/api/health` retried the LLM up to 5 × 6.5 s. Now ≤ 2 quick attempts, shared between concurrent callers; tests isolated from the real LLM. 10/10 pass. Likely also behind the 22 Oct `WinError 10053` drops on `/api/health` |
