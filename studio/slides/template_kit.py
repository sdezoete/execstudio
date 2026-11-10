"""Turn an uploaded company deck into a clean template plus the directions it carries (requires python-pptx).

Company templates arrive as ordinary decks: example slides, layouts with unhelpful names, and instructions
written on the slides, in text boxes parked beside the slide, in the speaker notes, in a placeholder's
prompt text, or drawn on the layouts themselves.

  inventory(data, is_potx)    layouts, example slides and every piece of guidance text, with where it was
  clean(data, is_potx)        the same masters, layouts, theme and fonts, with every slide and every guidance
                              shape removed -> (pptx bytes, removed[])
  as_potx(pptx_bytes)         the clean template saved as a .potx
  roles(inv), rules(inv)      built-in reading of which layout serves which purpose, and of the directions
  profile(inv, ai=None)       the two above merged with the AI's reading (validated), ready to store

Only structured settings come out of this (a layout name per role, a few limits and switches): the
guidance text itself is shown to the user, never passed to the storyline prompt as instructions, and
the example slides' content is never used as facts.
"""
import io
import re
import zipfile

from lxml import etree
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER

from . import pptx_engine as eng

ROLES = ("cover", "content", "agenda", "section", "closing")
USED_ROLES = ("cover", "content", "agenda")   # the roles an export builds slides on
RULE_KEYS = ("max_bullets", "max_headline_words", "max_slides", "agenda", "source_line")
# directions the studio follows anyway, which a piece of guidance can be marked as covered by
FOLLOWED = ("layout", "examples_removed", "theme_kept", "action_titles")
RULE_RANGES = {"max_bullets": (1, 8), "max_headline_words": (5, 30), "max_slides": (1, 40)}

# Text that is about the template rather than part of it. STRONG marks guidance wherever it appears
# (even in a title placeholder); WEAK only counts outside placeholders, where real slide content is rare.
_STRONG = re.compile(r"\b(instructions?|guidance|guidelines?|how to use|use this (layout|slide|template|page)|"
                     r"delete (this|these|all|before)|remove (this|these|all|before)|replace (this|with)|"
                     r"click to add|type (your|here)|insert (your|here|the)|example[:\s–-]|sample (slide|text|content)|"
                     r"lorem ipsum|placeholder text|do not (use|change|move|resize|edit)|note to (author|presenter|user))\b"
                     r"|إرشادات|تعليمات|مثال|احذف|استخدم هذ", re.I)
_WEAK = re.compile(r"\b(always|never|must|should|max(imum)?|at most|no more than|not more than|up to \d|"
                   r"keep (the|it|to)|tip|example|sample|guide)\b|يجب|لا تزيد|كحد أقصى", re.I)
# PowerPoint's own prompt texts on a layout ("Click to edit Master title style") are not guidance
_DEFAULT_PROMPT = re.compile(r"^(click to (edit|add)|edit master|second level|third level|fourth level|fifth level|"
                             r"انقر لتحرير|انقر لإضافة)", re.I)
_CHROME = (PP_PLACEHOLDER.DATE, PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.SLIDE_NUMBER)
_CALLOUT_GEOM = re.compile(r"callout|wedge|cloud", re.I)
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

_ROLE_WORDS = {
    "cover": r"\b(cover|title slide|opener|opening|front|start)\b|غلاف|الغلاف",
    "agenda": r"\b(agenda|contents|table of contents|overview|outline)\b|جدول الأعمال|المحتويات",
    "section": r"\b(section|divider|chapter|break|part \d)\b|فاصل|قسم",
    "closing": r"\b(closing|thank you|thanks|contact|q ?& ?a|questions|end slide|final slide)\b|شكرا|ختام",
    "content": r"\b(content|body|headline|title only|standard|std|text|main)\b|محتوى",
}
_ROLE_RES = {k: re.compile(v, re.I) for k, v in _ROLE_WORDS.items()}


# ------------------------------------------------------------------ reading shapes
def _text(shape):
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        return "\n".join(t for t in (_text(s) for s in shape.shapes) if t)
    if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        return "\n".join(p.text.strip() for p in shape.text_frame.paragraphs if p.text.strip())
    return ""


def _offcanvas(shape, sw, sh):
    """True when the shape sits beside the slide (its centre is off the page): instructions parked
    in the margin of the editing view, which no audience ever sees."""
    if shape.left is None or shape.width is None:
        return False
    cx, cy = shape.left + shape.width / 2, shape.top + shape.height / 2
    return not (0 <= cx <= sw and 0 <= cy <= sh)


def _callout(shape):
    geom = shape._element.find(".//" + _A + "prstGeom")  # noqa: SLF001
    return geom is not None and bool(_CALLOUT_GEOM.search(geom.get("prst", "")))


def _guidance_shape(shape, sw, sh):
    """Why a non-placeholder shape on a layout, master or slide is guidance, or "" when it is part of the
    design (a logo, a brand bar, a 'Confidential' mark)."""
    text = _text(shape)
    if _offcanvas(shape, sw, sh):
        return "beside the slide"
    if _callout(shape):
        return "a callout"
    if text and (_STRONG.search(text) or _WEAK.search(text)):
        return "an instruction box"
    return ""


def _short(text, n=90):
    t = " ".join(text.split())
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def _ph_kinds(layout):
    out = []
    for ph in layout.placeholders:
        t = ph.placeholder_format.type
        if t in _CHROME:
            continue
        out.append({PP_PLACEHOLDER.CENTER_TITLE: "center_title", PP_PLACEHOLDER.TITLE: "title",
                    PP_PLACEHOLDER.SUBTITLE: "subtitle", PP_PLACEHOLDER.BODY: "body",
                    PP_PLACEHOLDER.OBJECT: "body", PP_PLACEHOLDER.PICTURE: "picture",
                    PP_PLACEHOLDER.CHART: "chart", PP_PLACEHOLDER.TABLE: "table"}.get(t, "other"))
    return out


# ------------------------------------------------------------------ inventory
def _open(data, is_potx):
    """The uploaded file as a Presentation with its slides still in it (open_template_bytes clears them)."""
    if is_potx:
        data = _swap_type(data, b"presentationml.template.main+xml", b"presentationml.presentation.main+xml")
    from pptx import Presentation
    return Presentation(io.BytesIO(data))


def inventory(data, is_potx=False):
    prs = _open(data, is_potx)
    sw, sh = prs.slide_width, prs.slide_height
    guidance = []

    def note(text, where, layout=None, slide=None):
        text = text.strip()
        if text and not any(g["text"] == text and g["where"] == where for g in guidance):
            guidance.append({"text": text[:600], "where": where, "layout": layout, "slide": slide})

    layouts = []
    for m, master in enumerate(prs.slide_masters):
        for shp in master.shapes:
            if not shp.is_placeholder and _guidance_shape(shp, sw, sh) and _text(shp):
                note(_text(shp), "on the slide master")
        for lt in master.slide_layouts:
            name = lt.name.strip()
            for shp in lt.shapes:
                if shp.is_placeholder:
                    if shp.placeholder_format.type in _CHROME:
                        continue  # date, footer and slide number fields
                    prompt = _text(shp)
                    if prompt and not _DEFAULT_PROMPT.search(prompt):
                        note(prompt, "prompt text in layout '%s'" % name, layout=name)
                elif _guidance_shape(shp, sw, sh) and _text(shp):
                    note(_text(shp), "on layout '%s'" % name, layout=name)
            layouts.append({"name": name, "master": m, "placeholders": _ph_kinds(lt), "used_by": [], "example_titles": []})
    by_name = {lt["name"]: lt for lt in layouts}

    slides = []
    for i, s in enumerate(prs.slides, 1):
        lname = s.slide_layout.name.strip()
        title = ""
        for shp in s.shapes:
            text = _text(shp)
            if shp.is_placeholder and shp.placeholder_format.type in eng.TITLE_TYPES:
                title = text
                if _STRONG.search(text) and len(text.split()) > 5:  # not a bare heading ("How to use this template")
                    note(text, "title of example slide %d" % i, layout=lname, slide=i)
                continue
            if not text:
                continue
            if _offcanvas(shp, sw, sh):
                note(text, "beside example slide %d" % i, layout=lname, slide=i)
            elif _STRONG.search(text) or _directive(text) or (not shp.is_placeholder and _WEAK.search(text)):
                note(text, "on example slide %d" % i, layout=lname, slide=i)
        if s.has_notes_slide and s.notes_slide.notes_text_frame is not None:
            notes = s.notes_slide.notes_text_frame.text.strip()
            if notes:
                note(notes, "speaker notes of example slide %d" % i, layout=lname, slide=i)
        if lname in by_name:
            by_name[lname]["used_by"].append(i)
            if title:
                by_name[lname]["example_titles"].append(_short(title, 80))
        slides.append({"index": i, "layout": lname, "title": _short(title, 80)})
    return {"layouts": layouts, "slides": slides, "guidance": guidance, "fonts": theme_fonts(data)}


def theme_fonts(data):
    """Heading and body fonts from the theme's font scheme (never raises)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = etree.fromstring(z.read("ppt/theme/theme1.xml"))
        out = {}
        for tag, key in (("majorFont", "heading"), ("minorFont", "body")):
            el = xml.find(".//" + _A + tag + "/" + _A + "latin")
            if el is not None and el.get("typeface") and not el.get("typeface").startswith("+"):
                out[key] = el.get("typeface")
        return out
    except Exception:  # noqa: BLE001
        return {}


# ------------------------------------------------------------------ cleaning
def clean(data, is_potx=False):
    """Every slide and every guidance shape removed; masters, layouts, placeholders, theme, fonts and the
    design's own pictures and shapes kept. Returns (pptx bytes, ["what was removed", ...])."""
    prs = eng.open_template_bytes(data, is_potx)   # slides removed
    sw, sh = prs.slide_width, prs.slide_height
    removed = []
    for master in prs.slide_masters:
        parts = [("the slide master", master)] + [("layout '%s'" % lt.name.strip(), lt) for lt in master.slide_layouts]
        for where, part in parts:
            for shp in list(part.shapes):
                if shp.is_placeholder:
                    continue
                why = _guidance_shape(shp, sw, sh)
                if why:
                    text = _text(shp)
                    removed.append("%s%s on %s" % (why[0].upper() + why[1:], (": '%s'" % _short(text, 60)) if text else "", where))
                    shp._element.getparent().remove(shp._element)  # noqa: SLF001
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue(), removed


def _swap_type(data, old, new):
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            blob = src.read(item.filename)
            if item.filename == "[Content_Types].xml":
                blob = blob.replace(old, new)
            dst.writestr(item, blob)
    return out.getvalue()


def as_potx(pptx_bytes):
    return _swap_type(pptx_bytes, b"presentationml.presentation.main+xml", b"presentationml.template.main+xml")


# ------------------------------------------------------------------ built-in reading
def _role_texts(inv, layout):
    """Everything that says what a layout is for: its name, its example slides' titles, its guidance."""
    texts = [layout["name"]] + layout["example_titles"]
    texts += [g["text"] for g in inv["guidance"] if g["layout"] == layout["name"]]
    return texts


def _mentions(inv, layout, role):
    """Guidance anywhere that names this layout and the role: 'Use LAY_06 for all content slides'."""
    name = layout["name"].lower()
    return any(name in g["text"].lower() and _ROLE_RES[role].search(g["text"]) for g in inv["guidance"])


def roles(inv):
    """{role: layout name or None}. cover and content are always filled; the others only when something
    in the deck (a name, an example slide's title, an instruction) says so -- structure alone is not enough."""
    lts = inv["layouts"]
    if not lts:
        return {r: None for r in ROLES}
    most_used = max(lts, key=lambda lt: len(lt["used_by"]))
    first_layout = inv["slides"][0]["layout"] if inv["slides"] else None

    def score(lt, role):
        said = sum(bool(_ROLE_RES[role].search(t)) for t in _role_texts(inv, lt)) + 3 * _mentions(inv, lt, role)
        ph = lt["placeholders"]
        shape = 0
        if role == "cover":
            shape = 2 * ("center_title" in ph) + ("subtitle" in ph) + (lt["name"] == first_layout)
        elif role == "content":
            shape = 2 * (ph == ["title"]) + ("title" in ph and len(ph) <= 2) + (lt is most_used and bool(lt["used_by"]))
            shape -= 3 * ("center_title" in ph)
        return said, shape

    out = {}
    taken = set()
    for role in ("cover", "content"):
        best = max((lt for lt in lts if lt["name"] not in taken), key=lambda lt: (sum(score(lt, role)), score(lt, role)[0]),
                   default=lts[0])
        out[role] = best["name"]
        taken.add(best["name"])
    for role in ("agenda", "section", "closing"):
        cands = [(score(lt, role)[0], lt) for lt in lts if lt["name"] not in taken]
        said, lt = max(cands, key=lambda x: x[0], default=(0, None))
        out[role] = lt["name"] if said and lt is not None else None
        if out[role]:
            taken.add(out[role])
    return out


_LIMIT = r"(?:max(?:imum)?\.?|at most|no more than|not more than|up to|limit(?:ed)? to|no longer than)\s*(?:of\s*)?"
_RULE_RES = [
    ("max_bullets", re.compile(_LIMIT + r"(\d{1,2})\s*(?:bullet|point|line)s?|(\d{1,2})\s*(?:bullet|point)s?\s*"
                                         r"(?:max(?:imum)?|at most|or fewer|or less)", re.I)),
    ("max_headline_words", re.compile(r"(?:headline|title|message)s?\b[^.\n]{0,50}?" + _LIMIT + r"(\d{1,2})\s*words|"
                                      r"(?:headline|title|message)s?\b[^.\n]{0,50}?(\d{1,2})\s*words?\s*(?:max(?:imum)?|or fewer|or less)", re.I)),
    ("max_slides", re.compile(_LIMIT + r"(\d{1,2})\s*(?:content\s*)?slides|(\d{1,2})\s*slides\s*(?:max(?:imum)?|or fewer|or less)", re.I)),
]
_AGENDA = re.compile(r"\bagenda\b[^.\n]{0,60}\b(always|include|required|must|should|after the cover|second slide|start)\b|"
                     r"\b(always|include|add|must|should|start with)\b[^.\n]{0,40}\bagenda\b", re.I)
_SOURCE = re.compile(r"\bsources?\b[^.\n]{0,40}\b(always|must|should|state|cite|show|include|every|each)\b|"
                     r"\b(always|must|should|state|cite|show|include|every slide|each slide)\b[^.\n]{0,40}\bsources?\b", re.I)
_EXAMPLES = re.compile(r"\b(delete|remove)\b[^.\n]{0,40}\b(example|sample|instruction|guidance)|^\W*(example|sample)\b|"
                       r"replace (this |it )?with your own", re.I)
_THEME = re.compile(r"\b(company|corporate|brand|template'?s?)\s+(fonts?|colou?rs?|theme)\b|\b(do not|don't|never)\s+change\b"
                    r"[^.\n]{0,30}\b(fonts?|colou?rs?|theme|master)", re.I)
_ACTION = re.compile(r"\b(headline|title)s?\b[^.\n]{0,40}\b(key message|the message|finding|conclusion|so what)\b", re.I)


def _directive(text):
    """Text that states one of the limits the studio can follow ("Max 3 bullets per slide"): guidance even
    inside a placeholder, where softer wording is more likely example content."""
    return any(rx.search(text) for _, rx in _RULE_RES) or bool(_AGENDA.search(text) or _SOURCE.search(text))


def rules(inv):
    """({rule: value}, {guidance index: [rule, ...]}) read from the guidance with plain patterns."""
    found, applied = {}, {}
    cover = inv["slides"][0]["layout"] if inv["slides"] else None
    for i, g in enumerate(inv["guidance"]):
        hits = []
        for key, rx in _RULE_RES:
            m = rx.search(g["text"])
            if not m:
                continue
            if key == "max_headline_words" and g["layout"] and g["layout"] == cover and g["slide"] in (None, 1):
                continue  # a word limit for the cover title is not a limit for action titles
            val = int(next(x for x in m.groups() if x))
            lo, hi = RULE_RANGES[key]
            if lo <= val <= hi:
                found.setdefault(key, val)
                hits.append(key)
        if _AGENDA.search(g["text"]):
            found["agenda"] = True
            hits.append("agenda")
        if _SOURCE.search(g["text"]):
            found["source_line"] = True
            hits.append("source_line")
        if _EXAMPLES.search(g["text"]):
            hits.append("examples_removed")
        if _THEME.search(g["text"]):
            hits.append("theme_kept")
        if _ACTION.search(g["text"]):
            hits.append("action_titles")
        if hits:
            applied[i] = hits
    return found, applied


# ------------------------------------------------------------------ merged profile
def _valid_rules(raw):
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, (lo, hi) in RULE_RANGES.items():
        try:
            v = int(raw.get(key))
        except (TypeError, ValueError):
            continue
        if lo <= v <= hi:
            out[key] = v
    for key in ("agenda", "source_line"):
        if raw.get(key) is True:
            out[key] = True
    return out


def profile(inv, ai=None):
    """The stored reading of a template. ai: the model's JSON answer ({layouts, rules, applied}) or None;
    anything in it that does not fit (an unknown layout name, a limit out of range) is ignored and the
    built-in reading is used instead."""
    names = [lt["name"] for lt in inv["layouts"]]
    lay = roles(inv)
    found, applied = rules(inv)
    source = "rules"
    if isinstance(ai, dict):
        source = "llm"
        for role, name in (ai.get("layouts") or {}).items() if isinstance(ai.get("layouts"), dict) else []:
            if role in ROLES and (name in names or (name is None and role not in ("cover", "content"))):
                lay[role] = name
        found.update(_valid_rules(ai.get("rules")))
        for k, v in (ai.get("applied") or {}).items() if isinstance(ai.get("applied"), dict) else []:
            if str(k).isdigit() and int(k) < len(inv["guidance"]) and isinstance(v, list):
                keys = [x for x in v if x in RULE_KEYS + FOLLOWED]
                applied[int(k)] = sorted(set(applied.get(int(k), []) + keys))
    for role, name in lay.items():
        if role not in USED_ROLES:
            continue  # recognised, but the studio does not build section or closing slides: the user is told
        # an instruction about a role ("Always start with this cover slide"), on the layout chosen for that
        # role, on an example slide using it, or naming it, is followed by using that layout for the role
        for i, g in enumerate(inv["guidance"]):
            if name and _ROLE_RES[role].search(g["text"]) and (g["layout"] == name or name.lower() in g["text"].lower()):
                applied.setdefault(i, []).append("layout")
    guidance = [{"text": _short(g["text"], 240), "where": g["where"], "applied": sorted(set(applied.get(i, [])))}
                for i, g in enumerate(inv["guidance"])]
    return {"layouts": lay, "layout_names": names, "rules": found, "guidance": guidance,
            "examples": len(inv["slides"]), "fonts": inv["fonts"], "source": source}
