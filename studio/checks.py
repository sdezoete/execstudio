"""Checks on model output, applied before anything reaches a slide.

The LLM is good at rewriting and bad at noticing what it dropped, so these are
deterministic and conservative: when in doubt they reject, and the caller keeps
the original text.
"""
import re

MAX_HEADLINE_WORDS = 15
MIN_HEADLINE_WORDS = 5   # shorter reads as a topic label ("KPIs"), not a finding
TOPIC_LABEL = re.compile(r"^(overview|update|summary|introduction|agenda|review|background)\b", re.I)

_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_WORD = re.compile(r"[^\W\d_][\w&'-]*", re.UNICODE)
_PLACEHOLDER = re.compile(r"^\W*(evidence needed|add (content|source)|tbd|tbc|n/?a|lorem ipsum|placeholder)\b", re.I)


def _norm_num(s):
    return s.replace(",", "")


def numbers(text):
    """Every number in the text, thousands separators removed ("1,200" == "1200")."""
    return {_norm_num(m) for m in _NUM.findall(text or "")}


def names(lines):
    """Capitalised words that are not the first word of a line or sentence: names, places, months,
    products, acronyms. Lines written in Title Case are skipped (every word would count)."""
    out = set()
    for line in lines:
        words = _WORD.findall(line or "")
        caps = [w for w in words if w[0].isupper()]
        if len(words) >= 3 and len(caps) / len(words) > 0.6:
            continue
        for sentence in re.split(r"(?<=[.!?:;])\s+", line or ""):
            ws = _WORD.findall(sentence)
            out.update(w for w in ws[1:] if w[0].isupper() and len(w) > 1)
            if ws and ws[0].isupper() and len(ws[0]) > 1:  # an acronym leading the sentence is still a name
                out.add(ws[0])
    return out


def missing_facts(before_lines, after_lines):
    """Numbers and names in before_lines that no longer appear anywhere in after_lines."""
    after = " ".join(after_lines)
    lost = sorted(numbers(" ".join(before_lines)) - numbers(after))
    low = after.lower()
    lost += sorted(n for n in names(before_lines) if n.lower() not in low)
    return lost


def _squash(text):
    """Lower case, letters and digits only: "3.2 days – Average lead time" == "3.2 days: average lead-time"."""
    return re.sub(r"[\W_]+", "", (text or "").lower())


def is_placeholder(text):
    t = (text or "").strip()
    return not t or bool(_PLACEHOLDER.match(t)) or (t.startswith("[") and t.endswith("]"))


def headline_problem(headline):
    """Why a generated action title breaks Quality check's rules, or "" when it is fine."""
    n = len((headline or "").split())
    if not n or is_placeholder(headline):
        return "it is empty or a placeholder"
    if n > MAX_HEADLINE_WORDS:
        return "it has %d words; the maximum is %d" % (n, MAX_HEADLINE_WORDS)
    if n < MIN_HEADLINE_WORDS or TOPIC_LABEL.search(headline.strip()):
        return "it names a topic instead of stating the finding"
    return ""


_CHATTER = re.compile(r"\b(I (cannot|can't|can not|am unable|don't have|do not have)|please (share|provide|send)|"
                      r"as an AI|I need more (information|details|facts))\b", re.I)
_GENERIC_SOURCE = re.compile(r"^\W*(the )?(source documents?|supplied material|provided (material|documents?)|documents?)\W*$", re.I)


def clean_storyline(slides, has_material):
    """Model-isms that must not reach a slide: assistant chatter in speaker notes, and evidence cited
    as "source documents" (the prompt block's label, not a real source). Edits in place; returns slides."""
    for s in slides:
        if _CHATTER.search(s.get("notes") or ""):
            s["notes"] = ""
        ev = s.get("evidence") or {}
        if ev.get("source") and _GENERIC_SOURCE.match(ev["source"]):
            if has_material:
                ev["source"] = "Key facts and uploaded material"
            else:
                s["evidence"] = {"status": "needed", "source": "", "gap": "Add supporting data"}
    return slides


MAX_POINTS = 5
_CUR = r"(?:EUR|USD|SAR|GBP|AED|\$|€|£)?\s*"
_VS = re.compile(r"(?P<label>[A-Za-z][^\d;:]{1,60}?)\s*" + _CUR + r"(?P<a>\d[\d,]*(?:\.\d+)?)\s*(?:%|pts|m|k|bn|days?|h)?\s*"
                 r"(?:vs\.?|versus|against|compared with)\s*(?:the\s*)?(?:target|plan|budget|goal)?\s*(?:of\s*)?"
                 + _CUR + r"(?P<b>\d[\d,]*(?:\.\d+)?)", re.I)
_ABOVE = r"(?:above|over|exceed\w*|higher than)"
_BELOW = r"(?:below|under|short of|lower than)"
_ALL = re.compile(r"\b(?:all|every|each|both|three|four|five)\b[^.;:]{0,80}?\b(?P<dir>" + _ABOVE + "|" + _BELOW + r")\s+(?:the\s+)?(?:target|plan|budget|goal)", re.I)


def comparisons(lines):
    """Actual-vs-target pairs on a slide: [(label, actual, target, "above"|"below"|"on")]."""
    out = []
    for line in lines:
        for m in _VS.finditer(line or ""):
            a, b = float(m["a"].replace(",", "")), float(m["b"].replace(",", ""))
            out.append((m["label"].strip(" -–:,"), m["a"], m["b"], "above" if a > b else "below" if a < b else "on"))
    return out


def direction_problem(original_lines, title):
    """A headline that says all KPIs are above (or below) target when the slide's own figures say
    otherwise (test report N-03: cost EUR 4.10 vs 3.90 called "below target")."""
    pairs = [p for p in comparisons(original_lines) if p[3] != "on"]
    m = _ALL.search(title or "")
    if not pairs or not m:
        return ""
    claimed = "above" if re.match(_ABOVE, m["dir"], re.I) else "below"
    wrong = [p for p in pairs if p[3] != claimed]
    if not wrong:
        return ""
    facts = "; ".join("%s %s vs %s is %s target" % (lbl, a, b, d) for lbl, a, b, d in pairs)
    return "says they are all %s target, but the figures say: %s" % (claimed, facts)


_ASK_VERB = re.compile(r"^\W*(approve|endorse|decide|authori[sz]e|fund|agree|sign off)\b", re.I)


def slides_stating_ask(slides, decision):
    """Numbers (1-based) of the slides that state the ask: a decision slide, a line that opens with an
    ask verb ("Approve …"), or text holding most of the brief's decision wording. The single answer to
    "does a slide state the ask", shared by every check that needs it."""
    want = {w.lower() for w in _WORD.findall(decision or "") if len(w) > 3}
    out = []
    for i, s in enumerate(slides, 1):
        lines = [s.get("headline", "")] + list(s.get("body") or [])
        text = " ".join(lines).lower()
        if (s.get("kind") == "decision" or any(_ASK_VERB.match(x or "") for x in lines)
                or (want and sum(w in text for w in want) >= 0.6 * len(want))):
            out.append(i)
    return out


def rewrite_problem(original, rewrite):
    """Why a rewrite of one existing slide is unacceptable, or "" when it is fine.
    original: {title, body}; rewrite: {title, body}, where an empty title / None body means "unchanged"."""
    new_title = rewrite.get("title") or original.get("title") or ""
    new_body = rewrite["body"] if rewrite.get("body") is not None else list(original.get("body") or [])
    if rewrite.get("title") and is_placeholder(rewrite["title"]):
        return "replaced the title with placeholder text"
    if rewrite.get("title") and len(rewrite["title"].split()) > MAX_HEADLINE_WORDS:
        return "wrote a title of %d words; the maximum is %d" % (len(rewrite["title"].split()), MAX_HEADLINE_WORDS)
    if rewrite.get("body") is not None:
        if not rewrite["body"] and original.get("body"):
            return "deleted the main text"
        if any(is_placeholder(x) for x in rewrite["body"]):
            return "put placeholder text in the main text"
        if len(rewrite["body"]) > MAX_POINTS:
            return "returned %d points; the maximum is %d (combine points, keep every number)" % (len(rewrite["body"]), MAX_POINTS)
        new_flat = _squash(" ".join(rewrite["body"]))
        old_flat = _squash(" ".join(original.get("body") or []))
        copied = [x for x in original.get("other_text") or [] if len(_squash(x)) > 3
                  and _squash(x) in new_flat and _squash(x) not in old_flat]
        if copied:
            return "copied text from the slide's other boxes into the main text (%s); it is already on the slide" % "; ".join(copied[:3])
    before = [original.get("title") or ""] + list(original.get("body") or [])
    if rewrite.get("title"):
        wrong_way = direction_problem(before + list(original.get("other_text") or []), rewrite["title"])
        if wrong_way:
            return "wrote a title that " + wrong_way
    lost = missing_facts(before, [new_title] + new_body)
    if lost:
        shown = ", ".join(lost[:6]) + ("…" if len(lost) > 6 else "")
        return "dropped %s (%s)" % ("a number or name" if len(lost) == 1 else "%d numbers or names" % len(lost), shown)
    return ""
