"""Standard-library .pptx writer: the fallback engine when python-pptx is not installed.

Builds the Office Open XML package by hand (one master, one blank layout, native
shapes and text boxes, speaker notes, a classification label in every footer).
It cannot draw native charts or use a corporate .pptx template; the python-pptx
engine (pptx_engine.py) does both.
"""
import datetime as _dt
import io
import re
import zipfile
from xml.sax.saxutils import escape as _xesc

from . import layouts

NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NSDECL = 'xmlns:a="%s" xmlns:r="%s" xmlns:p="%s"' % (NS_A, NS_R, NS_P)
XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
CT = "application/vnd.openxmlformats-officedocument."

SLIDE_W, SLIDE_H = 12192000, 6858000      # 13.333 x 7.5 in (16:9)
_INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ARABIC = re.compile("[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")


def E(inches):
    return int(round(inches * 914400))


def esc(s):
    return _xesc(_INVALID_XML.sub("", str(s or "")))


# ---------------------------------------------------------------- canvas
class XmlCanvas:
    def __init__(self, tpl):
        self.colors = {"accent": tpl.get("accent", "1F47C9"), "ink": tpl.get("ink", "1A2421"),
                       "muted": tpl.get("muted", "5A6763"), "tile": tpl.get("tile", "EDF1EF"),
                       "warn": tpl.get("warn", "D9822B"), "white": "FFFFFF"}
        self.font = tpl.get("font", "Calibri")
        self.shapes = []
        self._id = 2

    def _nid(self):
        self._id += 1
        return self._id

    def para(self, text, size=16, bold=False, color=None, align="l", bullet=False, after=6):
        text = str(text or "")
        rtl = bool(_ARABIC.search(text))
        if rtl and align == "l":
            align = "r"
        attrs = ' algn="%s"' % align
        if rtl:
            attrs += ' rtl="1"'
        if bullet:
            attrs += ' marL="228600" indent="-228600"'
        ppr = '<a:pPr%s><a:spcAft><a:spcPts val="%d"/></a:spcAft>%s</a:pPr>' % (
            attrs, after * 100, '<a:buFont typeface="Arial"/><a:buChar char="&#8226;"/>' if bullet else "<a:buNone/>")
        rpr = ('<a:rPr lang="%s" sz="%d" b="%d" dirty="0"><a:solidFill><a:srgbClr val="%s"/></a:solidFill>'
               '<a:latin typeface="%s"/><a:cs typeface="%s"/></a:rPr>') % (
            "ar-SA" if rtl else "en-US", int(size * 100), 1 if bold else 0, color or self.colors["ink"],
            esc(self.font), esc(self.font))
        return "<a:p>%s<a:r>%s<a:t>%s</a:t></a:r></a:p>" % (ppr, rpr, esc(text))

    def _shape(self, x, y, w, h, paras=None, fill=None, line=None, geom="rect", anchor="t", inset=0.08):
        sid = self._nid()
        sppr = ('<a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="%s"><a:avLst/></a:prstGeom>'
                % (E(x), E(y), E(w), E(h), geom))
        sppr += ('<a:solidFill><a:srgbClr val="%s"/></a:solidFill>' % fill) if fill else "<a:noFill/>"
        sppr += ('<a:ln w="9525"><a:solidFill><a:srgbClr val="%s"/></a:solidFill></a:ln>' % line) if line else "<a:ln><a:noFill/></a:ln>"
        tx = ""
        if paras is not None:
            ins = E(inset)
            tx = ('<p:txBody><a:bodyPr wrap="square" lIns="%d" tIns="%d" rIns="%d" bIns="%d" anchor="%s" rtlCol="0">'
                  "<a:normAutofit/></a:bodyPr><a:lstStyle/>%s</p:txBody>") % (
                ins, ins, ins, ins, anchor, "".join(paras) or '<a:p><a:endParaRPr lang="en-US"/></a:p>')
        self.shapes.append(
            '<p:sp><p:nvSpPr><p:cNvPr id="%d" name="Shape %d"/><p:cNvSpPr%s/><p:nvPr/></p:nvSpPr><p:spPr>%s</p:spPr>%s</p:sp>'
            % (sid, sid, ' txBox="1"' if paras is not None and not fill else "", sppr, tx))

    def box(self, x, y, w, h, fill=None, line=None, geom="rect"):
        self._shape(x, y, w, h, None, fill, line, geom)

    def text(self, x, y, w, h, lines, size=16, bold=False, color=None, align="l", bullet=False,
             fill=None, line=None, geom="rect", anchor="t", inset=0.08):
        if isinstance(lines, str):
            lines = [lines]
        self._shape(x, y, w, h, [self.para(l, size, bold, color, align, bullet) for l in lines],
                    fill, line, geom, anchor, inset)

    def chart(self, x, y, w, h, spec):
        return False


AREA = (0.6, 1.75, 12.13, 4.75)


def _footer(c, idx, total, meta, slide=None):
    c.text(0.55, 7.02, 6, 0.35, meta["classification"].upper() + "  ·  " + meta["template_name"], size=9, color=c.colors["muted"])
    if idx:
        c.text(11.7, 7.02, 1.05, 0.35, "%d / %d" % (idx, total), size=9, color=c.colors["muted"], align="r")
    ev = (slide or {}).get("evidence") or {}
    if slide is None:
        return
    if ev.get("status") == "linked" and ev.get("source"):
        c.text(0.55, 6.62, 12.2, 0.35, "Source: " + ev["source"], size=9, color=c.colors["muted"])
    elif ev.get("status") != "linked":
        c.text(0.55, 6.62, 12.2, 0.35, "Evidence needed: " + (ev.get("gap") or "add source"), size=9, color=c.colors["warn"])


def _draw_slide(c, s, idx, total, meta):
    if s["kind"] == "title":
        c.box(0.6, 2.55, 1.2, 0.08, fill=c.colors["accent"])
        c.text(0.55, 2.75, 11.5, 1.7, s["headline"], size=40, bold=True)
        c.text(0.55, 4.5, 11.5, 0.6, (s.get("body") or [meta["audience"]])[0], size=18, color=c.colors["muted"])
        c.text(0.55, 5.1, 11.5, 0.5, meta["date"], size=14, color=c.colors["muted"])
        _footer(c, 0, total, meta)
        return
    c.box(0.6, 0.38, 0.6, 0.06, fill=c.colors["accent"])
    c.text(0.55, 0.5, 12.2, 1.15, s["headline"], size=26, bold=True)
    _footer(c, idx, total, meta, s)
    layouts.draw(c, s, AREA)


# ---------------------------------------------------------------- package parts
_GRP = ('<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm>'
        '<a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>')


def _slide_xml(shapes):
    return (XML_HEAD + "<p:sld %s><p:cSld><p:spTree>%s%s</p:spTree></p:cSld>"
            "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>") % (NSDECL, _GRP, "".join(shapes))


def _notes_xml(c, notes):
    paras = "".join(c.para(line, 12) for line in (notes or "").split("\n") if line.strip()) or '<a:p><a:endParaRPr lang="en-US"/></a:p>'
    return (XML_HEAD + '<p:notes %s><p:cSld><p:spTree>%s'
            '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/><p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr>'
            '<p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="381000" y="685800"/><a:ext cx="6096000" cy="3429000"/></a:xfrm></p:spPr></p:sp>'
            '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
            '<p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="685800" y="4343400"/><a:ext cx="5486400" cy="4114800"/></a:xfrm></p:spPr>'
            '<p:txBody><a:bodyPr/><a:lstStyle/>%s</p:txBody></p:sp>'
            '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>') % (NSDECL, _GRP, paras)


def _theme_xml(canvas, name="Studio"):
    k = canvas.colors
    scheme = "".join('<a:%s><a:srgbClr val="%s"/></a:%s>' % (k, v, k) for k, v in [
        ("dk1", "000000"), ("lt1", "FFFFFF"), ("dk2", k["ink"]), ("lt2", k["tile"]), ("accent1", k["accent"]), ("accent2", k["warn"]),
        ("accent3", k["muted"]), ("accent4", "2E8B57"), ("accent5", "8A6D3B"), ("accent6", "5B6B9A"),
        ("hlink", k["accent"]), ("folHlink", k["muted"])])
    fill3 = "<a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill>" * 3
    ln3 = "".join('<a:ln w="%d"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>' % w for w in (6350, 12700, 19050))
    eff3 = "<a:effectStyle><a:effectLst/></a:effectStyle>" * 3
    font = esc(canvas.font)
    return (XML_HEAD + '<a:theme xmlns:a="%s" name="%s"><a:themeElements><a:clrScheme name="%s">%s</a:clrScheme>'
            '<a:fontScheme name="%s"><a:majorFont><a:latin typeface="%s"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
            '<a:minorFont><a:latin typeface="%s"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
            '<a:fmtScheme name="%s"><a:fillStyleLst>%s</a:fillStyleLst><a:lnStyleLst>%s</a:lnStyleLst>'
            '<a:effectStyleLst>%s</a:effectStyleLst><a:bgFillStyleLst>%s</a:bgFillStyleLst></a:fmtScheme>'
            '</a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>') % (
        NS_A, name, name, scheme, name, font, font, name, fill3, ln3, eff3, fill3)


_CLRMAP = ('bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
           'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"')


def _master_xml():
    lvl = '<a:lvl1pPr><a:defRPr sz="%d"/></a:lvl1pPr>'
    return (XML_HEAD + '<p:sldMaster %s><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
            '<p:spTree>%s</p:spTree></p:cSld><p:clrMap %s/>'
            '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
            '<p:txStyles><p:titleStyle>%s</p:titleStyle><p:bodyStyle>%s</p:bodyStyle><p:otherStyle>%s</p:otherStyle></p:txStyles>'
            '</p:sldMaster>') % (NSDECL, _GRP, _CLRMAP, lvl % 3200, lvl % 1800, lvl % 1800)


def _layout_xml():
    return (XML_HEAD + '<p:sldLayout %s type="blank" preserve="1"><p:cSld name="Blank"><p:spTree>%s</p:spTree></p:cSld>'
            '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>') % (NSDECL, _GRP)


def _notes_master_xml():
    return (XML_HEAD + '<p:notesMaster %s><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>'
            '<p:spTree>%s</p:spTree></p:cSld><p:clrMap %s/></p:notesMaster>') % (NSDECL, _GRP, _CLRMAP)


def _rels(items):
    body = "".join('<Relationship Id="%s" Type="%s" Target="%s"/>' % (rid, typ if typ.startswith("http") else REL + typ, tgt)
                   for rid, typ, tgt in items)
    return XML_HEAD + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % body


def build(title, slides, meta, tpl):
    """Return .pptx bytes. meta: classification, template_name, audience, date, author."""
    n = len(slides)
    files = {}
    notes_ctx = XmlCanvas(tpl)

    for i, s in enumerate(slides, 1):
        c = XmlCanvas(tpl)
        _draw_slide(c, s, i, n, meta)
        files["ppt/slides/slide%d.xml" % i] = _slide_xml(c.shapes)
        files["ppt/slides/_rels/slide%d.xml.rels" % i] = _rels([
            ("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml"),
            ("rId2", "notesSlide", "../notesSlides/notesSlide%d.xml" % i)])
        notes = s.get("notes") or ""
        ev = s.get("evidence") or {}
        if ev.get("source"):
            notes += "\nSource: " + ev["source"]
        files["ppt/notesSlides/notesSlide%d.xml" % i] = _notes_xml(notes_ctx, notes)
        files["ppt/notesSlides/_rels/notesSlide%d.xml.rels" % i] = _rels([
            ("rId1", "notesMaster", "../notesMasters/notesMaster1.xml"),
            ("rId2", "slide", "../slides/slide%d.xml" % i)])

    base = XmlCanvas(tpl)
    files["ppt/theme/theme1.xml"] = _theme_xml(base, tpl.get("name", "Studio"))
    files["ppt/theme/theme2.xml"] = _theme_xml(base, "Notes")
    files["ppt/slideMasters/slideMaster1.xml"] = _master_xml()
    files["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = _rels([
        ("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml"), ("rId2", "theme", "../theme/theme1.xml")])
    files["ppt/slideLayouts/slideLayout1.xml"] = _layout_xml()
    files["ppt/slideLayouts/_rels/slideLayout1.xml.rels"] = _rels([("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")])
    files["ppt/notesMasters/notesMaster1.xml"] = _notes_master_xml()
    files["ppt/notesMasters/_rels/notesMaster1.xml.rels"] = _rels([("rId1", "theme", "../theme/theme2.xml")])

    pres_rels = [("rId1", "slideMaster", "slideMasters/slideMaster1.xml"),
                 ("rId2", "notesMaster", "notesMasters/notesMaster1.xml"),
                 ("rId3", "theme", "theme/theme1.xml"),
                 ("rId4", "presProps", "presProps.xml"),
                 ("rId5", "viewProps", "viewProps.xml"),
                 ("rId6", "tableStyles", "tableStyles.xml")]
    sld_ids = []
    for i in range(1, n + 1):
        rid = "rId%d" % (6 + i)
        pres_rels.append((rid, "slide", "slides/slide%d.xml" % i))
        sld_ids.append('<p:sldId id="%d" r:id="%s"/>' % (255 + i, rid))
    files["ppt/_rels/presentation.xml.rels"] = _rels(pres_rels)
    files["ppt/presentation.xml"] = (
        XML_HEAD + '<p:presentation %s saveSubsetFonts="1"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        '<p:notesMasterIdLst><p:notesMasterId r:id="rId2"/></p:notesMasterIdLst>'
        '<p:sldIdLst>%s</p:sldIdLst><p:sldSz cx="%d" cy="%d"/><p:notesSz cx="6858000" cy="9144000"/>'
        '<p:defaultTextStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:defaultTextStyle></p:presentation>') % (
        NSDECL, "".join(sld_ids), SLIDE_W, SLIDE_H)
    files["ppt/presProps.xml"] = XML_HEAD + "<p:presentationPr %s/>" % NSDECL
    files["ppt/viewProps.xml"] = XML_HEAD + '<p:viewPr %s><p:gridSpacing cx="76200" cy="76200"/></p:viewPr>' % NSDECL
    files["ppt/tableStyles.xml"] = XML_HEAD + '<a:tblStyleLst xmlns:a="%s" def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>' % NS_A

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files["docProps/core.xml"] = (
        XML_HEAD + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:title>%s</dc:title><dc:creator>%s</dc:creator><cp:keywords>%s</cp:keywords><cp:category>%s</cp:category>"
        '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>'
        "</cp:coreProperties>") % (esc(title), esc(meta.get("author", "Executive Presentation Studio")),
                                   esc(meta["classification"]), esc(meta["classification"]), now, now)
    files["docProps/app.xml"] = (
        XML_HEAD + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        "<Application>Executive Presentation Studio</Application><Slides>%d</Slides><Notes>%d</Notes>"
        "<PresentationFormat>Widescreen</PresentationFormat></Properties>") % (n, n)

    overrides = [
        ("/ppt/presentation.xml", CT + "presentationml.presentation.main+xml"),
        ("/ppt/slideMasters/slideMaster1.xml", CT + "presentationml.slideMaster+xml"),
        ("/ppt/slideLayouts/slideLayout1.xml", CT + "presentationml.slideLayout+xml"),
        ("/ppt/notesMasters/notesMaster1.xml", CT + "presentationml.notesMaster+xml"),
        ("/ppt/theme/theme1.xml", CT + "theme+xml"),
        ("/ppt/theme/theme2.xml", CT + "theme+xml"),
        ("/ppt/presProps.xml", CT + "presentationml.presProps+xml"),
        ("/ppt/viewProps.xml", CT + "presentationml.viewProps+xml"),
        ("/ppt/tableStyles.xml", CT + "presentationml.tableStyles+xml"),
        ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
        ("/docProps/app.xml", CT + "extended-properties+xml"),
    ]
    for i in range(1, n + 1):
        overrides.append(("/ppt/slides/slide%d.xml" % i, CT + "presentationml.slide+xml"))
        overrides.append(("/ppt/notesSlides/notesSlide%d.xml" % i, CT + "presentationml.notesSlide+xml"))
    files["[Content_Types].xml"] = (
        XML_HEAD + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>%s</Types>') % "".join(
        '<Override PartName="%s" ContentType="%s"/>' % o for o in overrides)
    files["_rels/.rels"] = _rels([
        ("rId1", "officeDocument", "ppt/presentation.xml"),
        ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml"),
        ("rId3", "extended-properties", "docProps/app.xml")])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", files.pop("[Content_Types].xml"))
        zf.writestr("_rels/.rels", files.pop("_rels/.rels"))
        for name in sorted(files):
            zf.writestr(name, files[name])
    return buf.getvalue()
