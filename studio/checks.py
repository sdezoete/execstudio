"""Checks on model output, applied before anything reaches a slide.

The LLM is good at rewriting and bad at noticing what it dropped, so these are
deterministic and conservative: when in doubt they reject, and the caller keeps
the original text.
"""
import re

MAX_HEADLINE_WORDS = 15
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
    if TOPIC_LABEL.search(headline.strip()):
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
    before = [original.get("title") or ""] + list(original.get("body") or [])
    lost = missing_facts(before, [new_title] + new_body)
    if lost:
        shown = ", ".join(lost[:6]) + ("…" if len(lost) > 6 else "")
        return "dropped %s (%s)" % ("a number or name" if len(lost) == 1 else "%d numbers or names" % len(lost), shown)
    return ""
