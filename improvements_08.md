# Fix status — build 1.5.0 (25 Oct 2026)

| Issue | Fix | Verified |
|-------|-----|----------|
| W-01 OOK / presentation type ignored | What applies now follows from the context chosen, not from the model: OOK Yes → PRES-09 PASS when a slide carries Political Risk Framework content (political / country / sovereign / geopolitical risk, PRF, or the Arabic terms), otherwise FAIL; COMP-09 NOT VERIFIABLE. OOK No → both NOT APPLICABLE. CMS → COMP-07 NOT VERIFIABLE, COMP-08 NOT APPLICABLE; Transaction → the reverse; Other → both NOT APPLICABLE | Test; live: the SAR 410m Oman acquisition gives PRES-09 FAIL ("no slide presents the Political Risk Framework"), listed under "Still to fix"; with CMS, COMP-07 is never "not a capital program item" |
| W-02 "Simplify" alone did nothing | A slide whose points sit in separate text boxes (an exported deck) is now simplified box by box, in place: same boxes, same order, each shortened. KPI tiles and short labels are left alone | Test; live: "Main text simplified (4 of 5 boxes)", every figure kept |
| W-03 uploaded figures flagged | Root cause: a CSV row "48200000,51000000" was read as one number (the comma taken as a thousands separator). Thousands commas now need groups of three digits. Spreadsheet raw values also match their display form (0.314 = 31.4%, 48200000 = 48.2m), and percentage changes between two sourced figures (5.5% miss, 14.6% gain) count as sourced. The retry now replaces only the flagged figures | Test; live: a storyline from a CSV alone uses its figures with nothing flagged; one run's charts in tens of millions (4.82 for 48.2m) are flagged for checking, deliberately |
| Gates | **Confirmed:** in this checklist the stage gate only concerns COMP-07 (CMS gate requirements) and COMP-08 (transaction gate requirements). Both depend on gate paperwork the app never sees, so the gate cannot change a PASS or FAIL. It now appears in their wording ("…gate requirements for Gate II cannot be confirmed from the deck") | Test; live |

Not changed: PRES-09 is not marked critical in the checklist, so an OOK deck without the Political Risk Framework is still "board-ready" with PRES-09 under "Still to fix". Making it critical for OOK decks is a governance decision.

Tests: 41 API + 10 HTTPS, all passing.

---

I'll run the untested settings on the new build: Operational vs Executive on the same brief, the Investor Relations template and an uploaded template, the remaining board contexts, each transform option on its own, real Word, Excel, PDF and CSV uploads, and export with the extras switched off. I'll also do a quick check of the round-7 findings.

All four file types are read correctly, including the Excel sheet name and the PDF text. Now a storyline built only from those files, with no facts typed into the brief:

That's fixed too: the fields now use `unicode-bidi: plaintext`, so Arabic lines lay out right-to-left on their own. Testing is done; adding this round to the report.

I tested the settings that had been missed, on the new build (1.4.0). Most work as intended, but two need fixing before the pilot.

**Working:**
- **Executive vs Operational:** both behave sensibly. The Operational deck adds an implementation roadmap and a risk slide, its Q&A asks "who owns it and by when?", and the quality check flags the missing owners and dates.
- **Templates:** Investor Relations, Board Pack and an uploaded template each apply their own colours and footer, and a wrong file type is rejected.
- **Source files:** Word, Excel, CSV and PDF are all read correctly. A storyline built only from those files used 19 figures, every one from the files.
- **Transform:** headlines-only edits the deck in place and keeps all slides. Template-only works in under a second.
- **Export:** PowerPoint-only and the full pack both download as expected.
- **Earlier fixes:** this build fixes the "not board-ready on a ready deck" summary, and six of the nine round-6 issues ("offset" bridges, Arabic figures check, Arabic file names, Arabic text direction, Arabic labels, and placeholders when the brief has no facts).

**To fix:**
- **OOK investments (W-01, Medium–High):** for a SAR 410m acquisition in Oman with OOK set to Yes, the Political Risk Framework requirement (PRES-09) came back "Not applicable". Its own explanation said "This is an OOK investment (Oman), but the deck does not present any Political Risk Framework content". So the deck shows as board-ready at 4.4/5 with the requirement unmet. The assessment also overrides the presentation type the user picks: with CMS selected, it still said "not a capital program item".
- **"Simplify the main text" on its own does nothing (W-02, Medium):** it reports "No change needed" on a slide full of wordy bullets. The same slide is simplified correctly when the template option is also ticked.
- **False warning on uploaded figures (W-03, Low):** the quality check warns that figures from the uploaded Excel and CSV files are "not in your facts".

The board gate setting (Gate 0, I, II, III) made no visible difference to any check. That may be intended, but worth confirming.

Once W-01 and W-02 are fixed, I'd consider it ready for an English and Arabic pilot. Round 8 is at the top of the report, with steps to reproduce each issue and where in the code to fix it.
