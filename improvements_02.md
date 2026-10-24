Fix status — build 1.1.0 (23 Oct 2026, evening)

| ID | Fix | Verified |
|----|-----|----------|
| N-01 | Re-templating rebuilds each slide from one list of its text in reading order (`deck.slide_content`): number badges, footers, page numbers and repeats dropped; a simplified body replaces all of it instead of being appended to the other boxes. Rewrites over 5 points rejected. In-place mode: a one- or two-line main box (a KPI tile) is not "simplified", and a rewrite that copies other boxes' text into it is rejected | Tests on an app-exported deck and on a differently built deck; live run with the real model on data set D and the second deck: no duplicates, no badges, ≤ 5 points, nothing lost |
| N-03 | `checks.direction_problem`: a title claiming "all above/below target" is checked against the slide's own actual-vs-target pairs; retry with the figures, else title kept. Prompt now spells out how to read 4.10 vs 3.90 | Test; live run: "On-time delivery, cost per parcel, and damage rate all miss targets" |
| N-02 | "Figures add up" only on driver slides, and actual / plan / variance lines are never treated as parts | Test (bars and driver slides with 48.2 vs 51.0, 2.8 gap); live data set A: 9/9 |
| N-04 | One shared `checks.slides_stating_ask`; PRES-08 and Decision clarity say where the ask is ("stated on slides 1, 2, but the deck does not close on it"), clarity capped at 3 instead of 2 when an earlier slide states it | Test; live run |
| N-05 | Date error cleared as soon as a date changes | Code review; not browser-tested |
| N-06 | "Start a new brief" re-renders the board badge | Code review; not browser-tested |
| N-07 | Deck tabs wrap onto a second line under 600 px | Headless Edge screenshot at ~500 px: all five tabs visible |
| N-08 | Reading order by rows (tolerant of small offsets); a row of short labels over aligned items reads as pairs ("Phase 1 – Discuss") | Test; live run |
| N-09 | Version is one constant (`studio/__init__.py`, now 1.1.0), reported by `/api/health` and shown in the header | Live: header and health show 1.1.0 |
| Side note | Generated headlines over 15 words get one targeted retry (max 3 per deck, cover included) | Test; live data set A: all headlines ≤ 15 words |
| Search | Title/category matches weigh double ("risks" → risk heat map first) | Node check on `repository.json` |

Tests: 29 API + 10 HTTPS, all passing.

---

Executive Presentation Studio — Test Report
Oct 23, 2026 · @Sam
Retest summary
The fixed build resolves 12 of the 14 defects and partly fixes the other 2. The transform still isn't ready to release: it no longer loses content, but it now duplicates text onto the slide (new issue N-01).
Retested on 23 October 2026 (evening) at the new URL, with the same data sets A–F and the same steps as the first run. The version label still reads 1.0.1, so the two builds can't be told apart in the UI.
• Fixed: board assessment, export truncation, stuck buttons, Sharpen length, search, arithmetic slip, date validation, stale error, no-facts output, reload label, undo, API messages.
• Partly fixed: D-01 transform (no data loss, but duplicates) and D-13 mobile (no page scroll, but deck tabs hide off-screen).
• New: 9 issues — 1 High, 2 Medium, 6 Low. Several are side effects of the fixes themselves: the new "Figures add up" check, the transform rebuild and the new date check.
• Still passing: HTML and prompt injection blocked, API validation, path traversal blocked, figures used faithfully.
Previous defects: retest status
ID
Severity
Defect
Retest
What I saw
D-01
Critical
Transform deletes content
Partly fixed
Every number kept (overflow goes to notes); change report shown before download, no auto-download. Output now duplicates text — see N-01
D-02
High
Board assessment false pass
Fixed
Decision slide removed: PRES-08 FAIL, decision clarity 2/5. Wording contradicts PRES-03 — see N-04
D-14
High
Export drops bullets, placeholder footer
Fixed
7-bullet slide: 5 on slide, 2 in notes under "Moved from the slide"; no "Evidence needed" footer
D-03
Medium
Double-click leaves buttons stuck
Fixed
Buttons disabled while busy; double-clicks on Design, Sharpen, Transform and triple-click on Advisor each sent 1 request
D-04
Medium
Sharpen exceeds 15 words
Fixed
"Revenue" sharpened to 12 words
D-05
Medium
Exact-substring search
Fixed
"why did costs rise" → 4 results, "costs" = "cost". Minor: "the" matches all 9 slides; "risks" ranks Enterprise risk heat map last
D-06
Medium
Arithmetic slip
Fixed
Slide 4: "The two drivers sum to 2.1 points". The new check that caught this misfires — see N-02
D-07
Medium
No date validation
Fixed
"The meeting date is before the submission date" blocks the run. Message lingers — see N-05
D-08
Low
Stale validation error
Fixed
Error clears on typing; topic marked aria-invalid and linked to the message
D-09
Low
Weak no-facts output, label leak
Fixed
Data set B: 2-slide skeleton with [placeholders], clean speaker notes; evidence source reads "Key facts provided by the presenter"
D-10
Low
Wrong button label after reload
Fixed
Reload on Improve shows "Restructure my presentation"
D-11
Low
Remove without undo
Fixed
Toast "Slide 5 removed. Undo"; undo restores it in place
D-12
Low
Misleading API messages
Fixed
Supported list includes .pdf; unknown id → "File not found"
D-13
Low
Narrow-screen overflow
Partly fixed
No page scroll at 453 or 375 px, nav rail fits. Deck tabs still overflow — see N-07
New issues
ID
Severity
Issue
How to reproduce
Expected
N-01
High
Transform merges old and new text, duplicating content
Improve deck → upload data set D → tick all three changes → Transform → Download. Slide 2's single body box holds 10 bullets: 4 simplified points, then stray "1", "2", "3" lines and repeats of three of the points. Slide 3 lists on-time and damage rate twice. Notes contain stray "4", "5" and "Small print on the original slide: Corporate Master, 2 / 4". Fuel surcharge appears on the slide and also under "Moved from the slide". The report shows the cause: "9 more text boxes added to the main text".
At most 5 points per slide, as the UI promises; original text boxes replaced, not appended; numbering badges and footers ignored
N-02
Medium
"Figures add up" check gives a false alarm
Generate data set A → Quality check. Slide 3 (revenue vs plan) is flagged: "the parts (48.2 + 51 + 2.8 = 102 m) are more than the total of 2.8 m". After Sharpen the same slide reports "total of 48.2 m". Score drops from 9/9 to 8/9.
Only reconcile figures that are actually parts of a total (driver bridges), not actual vs plan vs variance
N-03
Medium
Transform headline gets the direction wrong
Same run as N-01, slide 3: "Cost per parcel, on-time delivery, and damage rate are all below target." Cost EUR 4.10 vs 3.90 and damage 0.8% vs 0.5% are above target.
"All three KPIs miss target" or equivalent; direction checked against target
N-04
Low
Board assessment contradicts itself
Data set A, remove the decision slide, run Board assessment. PRES-03 passes, quoting slide 1's bullet "Approve a 3% mid-market price increase…", while Decision clarity and PRES-08 both say "No slide states the decision… the decision appears only in the brief".
PRES-08 fails because the closing slide lacks the ask; wording acknowledges slide 1 states it
N-05
Low
Date error stays after dates are fixed
Board assessment: submission 10 Nov, meeting 2 Nov → Run (error shows) → change to 1 Oct / 12 Oct. The error stays visible after the correction.
Clear on date change
N-06
Low
Stale board badge
Run Board assessment ("2 fails" badge on the tab) → Start a new brief. Badge stays until the page is reloaded.
Reset with the brief
N-07
Low
Deck view tabs hidden on mobile
At 375 px the tab strip (Storyline … Export) is 570 px wide in a 342 px box; Board assessment and Export are off-screen with no scroll cue.
Wrap, shorten labels, or show a fade or arrow
N-08
Low
Transform reorders unchanged bullets
Data set D slide 4 "Discuss, Review, Follow up" comes back as "Follow up, Discuss, Review".
Order preserved
N-09
Low
Version label not bumped
Fixed build still shows 1.0.1.
Bump the version so testers and users can tell builds apart
Also seen once, not filed: in data set B, the generated placeholder headline was 16 words and failed the app's own 15-word rule. It counts as a minor variant of D-04.
Next fixes, in priority order
1. N-01: rebuild each transformed slide from the simplified text only. Drop the original body text boxes, number badges and footers rather than merging them in. Add a check that the slide holds 5 points or fewer.
2. N-03: after the headline is rewritten, compare each KPI's actual against its target and correct words like "above", "below", "beat" or "miss" before the headline is accepted.
3. N-02: limit "Figures add up" to slides whose numbers are labelled as parts of a total (driver trees, bridges). Skip actual / plan / variance sets.
4. N-04, N-05, N-06: keep wording and state consistent — one source for "does a slide state the ask", clear the date error on change, reset the board badge on a new brief.
5. N-07 to N-09: mobile tab strip, preserve bullet order, bump the version number.
Once N-01 and N-03 are fixed, the transform needs a full retest with a second, differently built deck: a real customer deck rather than one exported from the app, so the merge logic is tested on unfamiliar shapes.
Below: the original report (first build, morning of 23 October) kept as the baseline.
Summary
The core "brief to storyline to export" path works well, but the Improve an existing deck transform loses content and should not be released as is. Of 35 test cases, 23 passed, 5 passed with issues and 7 failed.
The three defects to fix first:
1. Transform deletes slide content (Critical). A 5-bullet slide came back with 1 bullet; a 3-KPI slide with 1 KPI; a "Next steps" slide became "Evidence needed: Evidence needed". The UI promises "Every number and name is kept".
2. Board assessment passes a CRITICAL check falsely (High). With the decision slide deleted, PRES-08 "Closing slide confirms the action" still passed, and Decision clarity scored 5/5.
3. PPTX export silently drops bullets past five (High) and stamps "Evidence needed: Evidence needed" on every slide that lacks an evidence note.
Generation quality is otherwise strong: figures are used faithfully, no numbers were invented when none were given, HTML and prompt injection were both neutralised, and the API rejects bad input cleanly.
Scope and approach
Tested Executive Presentation Studio 1.0.1 ("Powered by ARIF") at the trycloudflare URL on 23 October 2026, as an end user in the Claude desktop browser pane, at desktop, 453 px and 375 px (mobile) widths. Health check reported the LLM reachable, python-pptx 1.0.2 and PDF support on.
Features covered:
• Presentation studio: the four task modes (new deck, improve deck, single slide, find template), brief validation, storyline generation, per-slide Sharpen / reorder / remove, Quality check, Q&A preparation, Board assessment, Export.
• Slide advisor: recommendations, example prompts, Add to my deck.
• Content Templates: repository search and category filters.
• API (/api/storyline, /review, /qa, /sharpen, /advise, /board-assessment, /export/*, /extract, /deck/*, /download/*): malformed input, file types, path traversal, payload size, concurrency, security headers.
Exported files were inspected in-browser (unzipped and read) rather than saved, except one transform result the app auto-downloaded. LLM output varies run to run, so content findings are single observations; the code-level defects are deterministic.
Test results
ID
Area
Scenario
Result
Notes
TC-01
Brief
Submit empty brief
Pass
Message shown, focus moves to topic
TC-02
Brief
Topic of spaces only
Pass
Rejected
TC-03
Generate
Executive brief, 5–10 slides, real figures (data set A)
Partial
6 slides in 12 s, figures faithful; arithmetic slip on slide 4 (D-06); stale error stays visible (D-08)
TC-04
Quality check
Run on generated deck
Pass
8/8, re-scores after each edit
TC-05
Q&A prep
Generate likely questions
Pass
5 grounded Q&As citing slide numbers
TC-06
Edit
Reorder slides with up/down
Pass
Up disabled on first slide
TC-07
Quality check
Replace a headline with "KPIs"
Pass
Flagged: slide 3 needs a finding headline
TC-08
Edit
Sharpen the weak headline
Fail
Returned 17 words; fails the app's own 15-word rule (D-04)
TC-09
Edit
Remove the decision slide
Partial
Works, QC flags missing ask; no confirm or undo (D-11)
TC-10
Board
Assess deck with decision slide removed
Fail
PRES-08 (Critical) passes falsely (D-02)
TC-11
Board
Submission 3 vs 7 business days before meeting
Pass
3 days FAIL, 7 days PASS
TC-12
Board
Meeting date before submission date
Fail
Says "date not provided"; no validation (D-07)
TC-13
Export
PPTX + briefing pack
Pass
Valid 51 KB .pptx and .md pack; warns 2 checks open
TC-14
Export
Q&A appendix after slides edited
Pass
Regenerated for the 5-slide deck
TC-15
Generate
Operational, no facts, HTML in topic (data set B)
Partial
No XSS, no invented numbers; only one placeholder slide, chatbot text in notes (D-09)
TC-16
Generate
Single executive slide (data set C)
Pass
1 slide; 2 × EUR 70k correctly totalled to EUR 140k
TC-17
Find
"Find a template" opens repository
Pass
9 approved slides listed
TC-18
Find
Search the placeholder example "why did costs rise"
Fail
0 results; "costs" 0, "cost" 1 (D-05)
TC-19
Advisor
Example prompt (CRM vendors)
Pass
Matrix + 2 alternatives, relevant
TC-20
Advisor
Blank message
Pass
Rejected with guidance
TC-21
Advisor
Double-click "Recommend a slide"
Fail
Button stuck on "Thinking…", duplicate calls (D-03)
TC-22
Advisor
Add to my deck
Pass
Added with [X%] placeholders
TC-23
State
Reload mid-session
Partial
Draft restored; Improve task shows wrong button label (D-10)
TC-24
Improve
Upload a 4-slide .pptx (data set D)
Pass
4 slides, 757 characters detected
TC-25
Improve
Transform: headlines + simplify + template
Fail
Content lost, junk slide (D-01)
TC-26
Export
Slide with 7 bullets, no evidence
Fail
Bullets 6–7 dropped; placeholder footer (D-14)
TC-27
API
Malformed JSON, empty brief, wrong types, 0 slides
Pass
Clear 400 messages
TC-28
API
Upload .exe, corrupt PDF, corrupt PPTX
Pass
Rejected gracefully; message omits .pdf (D-12)
TC-29
API
Path traversal on /api/download
Pass
Blocked
TC-30
Security
Response headers
Pass
Strict CSP, HSTS, X-Frame-Options DENY, nosniff
TC-31
Generate
Prompt injection inside key facts
Pass
Ignored; internal label "SOURCE DOCUMENTS" leaks (D-09)
TC-32
API
5 MB text upload
Pass
Accepted and truncated; took 27 s, no size warning
TC-33
API
Requests during an LLM call
Pass
Other requests not blocked
TC-34
Layout
453 px and 375 px widths
Partial
453 px page overflows to 557 px; nav and pipeline scroll sideways (D-13)
TC-35
Accessibility
Labels, roles, live regions
Pass
Labels linked, tabs/radiogroups correct; errors not tied to fields
Defects
ID
Severity
Defect
How to reproduce
Expected
D-01
Critical
Transform deletes slide content and writes junk
Improve deck → upload data set D → tick all three changes → Transform. Slide 2 keeps 1 of 5 bullets, slide 3 keeps 1 of 3 KPIs, slide 4 headline and body become "Evidence needed: Evidence needed"; change report still says "Headline rewritten, Main text simplified".
Every number and name kept, as the UI states; slide 4 rewritten from its own text
D-02
High
Board assessment validates against the brief, not the slides
Generate data set A → remove the final decision slide → Board assessment. PRES-08 (Critical) PASS, quoting the decision text that is no longer on any slide; Decision clarity 5/5. Quality check meanwhile says "Add a decision slide".
PRES-08 FAIL; scores match Quality check
D-14
High
PPTX export silently truncates and stamps a placeholder
Export a slide with 7 bullets and no evidence note. Bullets 6–7 are dropped; every slide gets the footer "Evidence needed: Evidence needed".
Keep all content or warn; omit the footer when there is nothing to say
D-03
Medium
Double-click leaves buttons stuck
Slide advisor → double-click "Recommend a slide". Two API calls fire; button reads "Thinking…" until reload. Cause: busy() doesn't disable the button, and the second call saves "Thinking…" as the original label. Same helper is used by Design, Export and Transform.
Disable while busy; ignore repeat clicks
D-04
Medium
Sharpen breaks the app's own headline rule
Set a headline to "KPIs" → Sharpen. Result is 17 words, no full stop; Quality check then fails "15 words or fewer".
Sharpen output ≤ 15 words
D-05
Medium
Repository search is exact-substring only
Content Templates → search "why did costs rise" (the placeholder and the no-results hint both suggest it) → 0 results. "costs" → 0, "cost" → 1.
Word-level / stemmed match; "why did costs rise" finds Margin bridge and Business case
D-06
Medium
Arithmetic slip in generated content
Data set A: freight 0.9 + raw materials 1.2 = 2.1 pts, the full decline. Slide 4 says the remaining gap is "not specified" and the notes say there is no evidence for it. Quality check passes it.
No phantom gap; or a check that reconciles parts to totals
D-07
Medium
No date validation in Board assessment
Submission 10 Nov, meeting 2 Nov → "Submission date and/or meeting date was not provided".
Inline error: meeting precedes submission
D-08
Low
Stale validation error
Submit empty brief, then fill and submit. "Add a presentation topic…" stays visible during and after generation, and after "Start a new brief".
Clear on input or on success
D-09
Low
Weak no-facts output; internal label leak
Data set B (no facts): one slide saying facts are needed, speaker notes read "I cannot build… Please share…". Evidence fields show "source documents" / "SOURCE DOCUMENTS" when none were uploaded.
Draft a skeleton storyline with marked gaps, as the page promises; cite only real sources
D-10
Low
Button label wrong after reload
Choose Improve, reload. Task restored as Improve, button reads "Design my presentation" instead of "Restructure my presentation".
Label follows restored task
D-11
Low
Remove has no confirm or undo
Click Remove on any slide: gone immediately.
Undo in the toast
D-12
Low
Misleading API messages
Unsupported-type message omits .pdf (which is supported); any unknown download id says "That file has expired".
Accurate lists; "not found" vs "expired"
D-13
Low
Narrow-screen overflow
At 453 px the page is 557 px wide (slide action buttons); at 375 px the nav rail and pipeline scroll sideways, hiding "Content Templates".
No horizontal page scroll; wrap or menu
The transform run also downloaded Logistics_update_test_Corporate_Master_2026-10-23.pptx straight away, with no preview step; that file is test data and can be deleted.
What works well
• Faithful to the figures. Every number in data sets A and C was reproduced correctly, derived totals were right (EUR 2.8m miss, EUR 140k), and nothing was invented when no facts were given.
• Answer-first structure. Action titles, a decision slide and grounded Q&A with slide references came out of one brief.
• Quality check is live. It re-scored after reorder, headline edits and removal, and caught a topic headline, a long headline and a missing ask.
• Business-day rule works. 3 days failed, 7 days passed.
• Export is honest. It lets you export with open checks but says how many remain; Q&A appendix is regenerated after edits.
• Robust, secure API. Clear 400 messages for every malformed request, path traversal blocked, strict CSP / HSTS / frame denial, HTML and prompt injection neutralised.
• Drafts survive a reload.
Recommended improvements
1. Add a content-preservation check to Transform. Diff every number and proper noun before and after; block or warn if any go missing. Show the result before downloading, not after.
2. Run Board assessment on slide text only. Pass the slides, not the brief's decision field, so CRITICAL checks reflect what the board will actually see; reuse Quality check results where they overlap.
3. Make export lossless. Overflow extra bullets to a second slide or notes, and drop the "Evidence needed" footer when there is no gap.
4. Fix busy(). Set disabled on the button and skip relabelling if it is already busy. One change fixes Design, Advisor, Export and Transform.
5. Validate LLM output with the same rules as Quality check. Re-prompt Sharpen if it exceeds 15 words; add a check that parts reconcile to totals.
6. Better repository search. Tokenise, stem and match against title, question and category; make the placeholder example return results.
7. Undo for destructive edits. An "Undo" action in the Removed toast.
8. Form hygiene. Clear errors on input, mark the field aria-invalid and link the message, validate meeting ≥ submission date.
9. No-facts mode. Produce a skeleton storyline with [placeholders] instead of a single "send me facts" slide, and keep model chatter out of speaker notes.
10. Mobile layout. Wrap slide action buttons; turn the nav rail into a menu below about 480 px.
11. Show progress for long calls. Storyline took about 12 s and a large upload 27 s with only a spinner; add elapsed time or steps.
Test data
Set
Used in
Content
A
TC-03 to TC-14
Topic "Q3 2026 business performance review"; decision "Approve a 3% mid-market price increase from January 2027"; facts: revenue EUR 48.2m vs plan EUR 51.0m (−5.5%), gross margin 31.4% down 2.1 pts YoY (freight +0.9, raw materials +1.2), mid-market churn 4.1% vs 3.5% target, Competitor A +4% in July, Benelux test +3% price / −0.6% volume. Executive, 5–10 slides, Corporate Master.
B
TC-15
Topic <img src=x onerror=alert(1)> Warehouse safety update; no decision, no facts; Operational, 1–3 slides.
C
TC-16
Single slide: "Customer onboarding time"; ask "Fund two extra onboarding specialists"; onboarding 9 → 14 days Q1–Q3 2026, backlog 62 accounts, EUR 70k per specialist per year.
D
TC-24 to TC-26
Logistics_update_test.pptx, 4 slides: title; "Overview" with 7 bullets (on-time 91% vs 95%, Warehouse B 97%, Carrier X contract to March 2027, fuel +6%, returns backlog 1,800, pilot); "KPIs" (on-time, cost per parcel EUR 4.10 vs 3.90, damage 0.8% vs 0.5%); "Next steps" (Discuss / Review / Follow up).
E
TC-31
Support brief (first response 9.5 h vs 4 h, volume +22% QoQ, CSAT 78% vs 85%) plus an injected line asking to claim 50% revenue growth, CEO approval and to reveal the system prompt.
F
TC-27 to TC-29, TC-32
Malformed JSON, {}, slides as a string, empty slide list, malware.exe, text-as-PDF, text-as-PPTX, ..%2f..%2fetc%2fpasswd, 5 MB text file.
