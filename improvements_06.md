# Fix status — build 1.4.0 (24 Oct 2026)

Note: the full round-6 report (U-01 to U-09, and the replacement function it mentions) was never in the project; these fixes are based on the summary below.

| Issue | Fix | Verified |
|-------|-----|----------|
| High: "not board-ready because of PRES-07" on a board-ready deck | The summary is now settled in both directions: a passing deck opens with "Board-ready: no critical check fails. Still to fix: …" (non-critical FAIL/WARNING items) and model sentences claiming a critical failure or (not-)readiness are dropped. The prompt names the only critical checks (PRES-03, PRES-08) and says a missing progress gauge is never critical | Test with a mock reviewer that writes the round-7 sentence; live, 3 of 3 runs on an investment deck: "Board-ready: no critical check fails. Still to fix: PRES-07 (presentation includes a progress gauge)" |
| PRES-03 fails by mistake (~1 in 10) | Decided from the same "which slides state the ask" as PRES-08: if the cover or first content slide states the ask it cannot FAIL; with a decision in the brief and no opening ask it cannot PASS. "For information / guidance / we ask" count as asks | Test (4 cases); live 3 of 3 PASS |
| "Offset" bridges add instead of subtract | Parts with offset wording ("costs offset SAR 9m", "partly offset by", "drag of") are subtracted | Tests both ways |
| Arabic: figures check did not work | Arabic-Indic digits, ٫ ٬ ٪, units (مليون، مليار، ألف، نقطة) and the keywords the rules use (total, change, contribution, offset, plan, share, زائد / يساوي) are mapped before checking, allowing for attached prefixes and suffixes | 14 Arabic cases both ways; live: an Arabic storyline scores 9/9 and a wrong Arabic bridge is caught |
| Arabic: downloads named `____2026_….pptx` | The page now prefers the UTF-8 `filename*`; the ASCII fallback reads `presentation_<date>.pptx` | Test; live: "مراجعة_أداء_الربع_الثالث_…pptx" |
| Chart mixing SAR and % | One unit per chart: series in a different unit from the first are dropped; the prompt asks for one unit | Test |
| Left-to-right editor fields for Arabic | Text fields take each line's direction from its own text (`unicode-bidi: plaintext`) | Code review; not browser-tested |
| English labels on Arabic slides | Source / Evidence gap / Moved from the slide / Phase n / Decision required / matrix and risk axes / [Add content] / transform notes are written in Arabic on Arabic slides | Test; live: no English labels left on an exported Arabic deck |
| Invented plan when the brief has no facts | Every storyline figure must come from the brief or material (or simple arithmetic on two of them, such as 51.0 − 48.2 = 2.8 or 2 × 70k = 140k; small whole numbers like Q1 exempt; years must be given). One retry naming the figures, then the slide is marked "evidence needed: check figures …". A slide whose evidence is still needed no longer shows a pseudo-source ("No source documents provided") | Tests; live: the no-facts brief gave [placeholders], no invented figures |

Also: the PowerPoint-saved deck the summary calls untested has been in the tests since 1.3.0 (`tests/fixtures/powerpoint_northwind.pptx`: theme, SmartArt, chart with embedded workbook, table, picture, group, speaker notes).

Tests: 38 API + 10 HTTPS, all passing.

---

For this final round I'll retest the nine round-6 issues (U-01 to U-09), rerun the standard suite and the new data sets, run a regression pass, and finish with a release verdict in the report.

The regression checks are clean, and the Arabic file-name bug is unchanged. Writing the final round and release verdict into the report.

I put a code snippet in the report, so I'll check it against the four summaries the app actually produced.

Clean now. Updating the snippet in the report:

This build is the same as round 6, so none of the round-6 issues are fixed yet. It still reports version 1.3.1, the front-end code is identical, and nothing in your project folder has changed since I read it before round 6. Testing it again did turn up one new problem worth fixing before anyone uses the app.

**New finding (High):** on a board-ready deck, the summary says "This deck is not board-ready because it fails the critical PRES-07 requirement". This happened in 4 of 4 runs on the investment deck, while the score said 4.0–4.7/5 with no critical failures. Two things cause it:
- **The prompt:** it tells the AI to open with "not board-ready" whenever a critical check fails. The AI keeps treating the progress gauge (PRES-07) as critical, even though only PRES-03 and PRES-08 are marked critical.
- **The code:** `_settle_summary` in `services.py` cleans up the summary only when the deck fails, so on a passing deck the wrong sentence reaches the page.

The progress gauge was missing in every deck I tested, so most good decks would show this. The report has a tested replacement for that function. It produces, for example: "Board-ready: no critical check fails. Still to fix: PRES-07 (presentation includes a progress gauge)."

**Still open from round 6:**
- **Opening-slide check (PRES-03) can fail by mistake:** it passed in all 7 runs this time, so it happens about 1 run in 10.
- **"Offset" bridges get false alarms:** "costs offset SAR 9m" is added instead of subtracted.
- **Arabic:** the figures check doesn't work on Arabic slides, and Arabic decks download as `____2026_….pptx`.
- **Smaller items:** a chart mixing SAR and %, left-to-right editor fields for Arabic, an English label on Arabic slides, and an invented plan when the brief has no facts.

**What holds:** the figures check caught 22 of 22 English mismatches across both test sets. Storylines use only your figures, the transform keeps every number, chart and table, and the security checks have passed in every round.

**Verdict:** with the summary fix, it's ready for a pilot with English decks. Arabic decks and a wider release should wait for the three Medium issues above. A deck saved by PowerPoint itself, with SmartArt, pictures and speaker notes, has still never been tested.

The final verdict, round 7 results, the fix and a seven-round overview are at the top of the report.
