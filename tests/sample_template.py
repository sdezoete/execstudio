"""Builds a simulated company template: the kind of deck people upload as "the template".

No real company file can leave the organisation, so this reproduces what they look like:
  - layouts with unhelpful names (LAY_01 Opener, LAY_06 Std headline, ...)
  - example slides with real-looking content and figures (which must never reach a new deck)
  - instructions on the slides, in text boxes parked beside the slide, and in the speaker notes
  - a callout and an off-page note drawn on a layout itself, and a custom prompt in a placeholder
  - a logo and a 'Company Confidential' mark on the master, which are design and must stay
  - its own theme fonts and accent colour

    python tests/sample_template.py company_template.pptx
"""
import io
import sys
import zipfile

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from sample_deck import _png

NAMES = {0: "LAY_01 Opener", 1: "LAY_02 Text", 2: "LAY_03 Break", 3: "LAY_04 Two col", 4: "LAY_05 Compare",
         5: "LAY_06 Std headline", 6: "LAY_07 Free", 7: "LAY_08 Caption", 8: "LAY_09 Picture",
         9: "LAY_10 Vertical", 10: "LAY_11 Vertical title"}
HEAD_FONT, BODY_FONT, ACCENT = "Georgia", "Segoe UI", "7A1F3D"

EXAMPLE_FIGURES = ("SAR 48m", "12%", "4,310")   # on the example slides only


def _copy_to(part, shape):
    """python-pptx can only add shapes to slides: draw on a slide, then move the element onto a layout/master."""
    el = shape._element  # noqa: SLF001
    tree = part.shapes._spTree  # noqa: SLF001
    el.xpath(".//p:cNvPr")[0].set("id", str(max([int(x) for x in tree.xpath(".//p:cNvPr/@id")] or [1]) + 1))
    if hasattr(shape, "image"):  # the picture's image must be related to the part it now sits on
        _, rid = part.part.get_or_add_image_part(io.BytesIO(shape.image.blob))
        el.blipFill.blip.rEmbed = rid
    tree.append(el)


def build():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    for i, lt in enumerate(prs.slide_layouts):
        lt._element.cSld.set("name", NAMES[i])  # noqa: SLF001
    lt = {i: prs.slide_layouts[i] for i in NAMES}
    scratch = prs.slides.add_slide(lt[6])   # drawing surface, removed again below

    # master: logo and confidentiality mark (design), drawn top right and bottom left
    _copy_to(prs.slide_master, scratch.shapes.add_picture(io.BytesIO(_png(120, 40, (122, 31, 61))), Inches(11.6), Inches(0.3), Inches(1.2)))
    conf = scratch.shapes.add_textbox(Inches(0.4), Inches(7.05), Inches(3), Inches(0.3))
    conf.text_frame.text = "Company Confidential"
    _copy_to(prs.slide_master, conf)

    # the content layout: a callout over the slide and a note parked beside it, plus a custom title prompt
    callout = scratch.shapes.add_shape(MSO_SHAPE.RECTANGULAR_CALLOUT, Inches(8), Inches(3), Inches(3.5), Inches(1.2))
    callout.text_frame.text = "The headline is the key message"
    _copy_to(lt[5], callout)
    beside = scratch.shapes.add_textbox(Inches(13.8), Inches(1), Inches(3), Inches(2))
    beside.text_frame.text = "Guideline: maximum 4 bullet points per slide"
    _copy_to(lt[5], beside)
    brand_bar = scratch.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(7.4), prs.slide_width, Inches(0.1))
    _copy_to(lt[5], brand_bar)   # a plain brand bar: design, stays
    lt[5].placeholders[0].text_frame.text = "Action title: state the message, at most 12 words"

    sl = prs.slides._sldIdLst  # noqa: SLF001
    prs.part.drop_rel(sl[0].rId)
    sl.remove(sl[0])

    # 1 cover
    s = prs.slides.add_slide(lt[0])
    s.shapes.title.text = "Project Falcon"
    s.placeholders[1].text = "Board of Directors | 12 March 2026"
    s.notes_slide.notes_text_frame.text = "Always start with this cover slide. Subtitle: audience and date."
    # 2 agenda
    s = prs.slides.add_slide(lt[1])
    s.shapes.title.text = "Agenda"
    s.placeholders[1].text = "Context\nPerformance\nOutlook\nDecision"
    s.notes_slide.notes_text_frame.text = "Always include an agenda after the cover."
    # 3 a content example, with figures, an on-slide example label and a sticky note beside the slide
    s = prs.slides.add_slide(lt[5])
    s.shapes.title.text = "Revenue grew 12% to SAR 48m on 4,310 new contracts"
    cd = CategoryChartData()
    cd.categories = ["Q1", "Q2", "Q3"]
    cd.add_series("Revenue, SAR m", (39.0, 43.5, 48.0))
    s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.8), Inches(1.9), Inches(7), Inches(4.5), cd)
    tag = s.shapes.add_textbox(Inches(8.2), Inches(2), Inches(4), Inches(0.6))
    tag.text_frame.text = "EXAMPLE – replace with your own content"
    sticky = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(13.6), Inches(2), Inches(3), Inches(2))
    sticky.text_frame.text = "Use LAY_06 Std headline for all content slides. Every slide must state its source."
    # 4 section break
    s = prs.slides.add_slide(lt[2])
    s.shapes.title.text = "Outlook"
    s.notes_slide.notes_text_frame.text = "Section divider between chapters."
    # 5 how-to slide
    s = prs.slides.add_slide(lt[1])
    s.shapes.title.text = "How to use this template"
    s.placeholders[1].text = ("Keep the deck to no more than 12 slides.\nUse the company fonts; do not change the theme.\n"
                              "Delete all example slides before sending.")
    # 6 closing
    s = prs.slides.add_slide(lt[6])
    box = s.shapes.add_textbox(Inches(1), Inches(3), Inches(8), Inches(1))
    box.text_frame.text = "Thank you"
    box.text_frame.paragraphs[0].runs[0].font.size = Pt(40)
    s.notes_slide.notes_text_frame.text = "Closing slide: contact details of the presenter."

    buf = io.BytesIO()
    prs.save(buf)
    return _theme(buf.getvalue())


def _theme(data):
    """Give the theme its own fonts and accent colour (python-pptx has no API for the theme part)."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            blob = src.read(item.filename)
            if item.filename == "ppt/theme/theme1.xml":
                text = blob.decode("utf-8")
                major = text.index("<a:majorFont>")
                minor = text.index("<a:minorFont>")
                text = (text[:major] + text[major:minor].replace('<a:latin typeface="Calibri"', '<a:latin typeface="%s"' % HEAD_FONT, 1)
                        + text[minor:].replace('<a:latin typeface="Calibri"', '<a:latin typeface="%s"' % BODY_FONT, 1))
                a1 = text.index("<a:accent1>")
                end = text.index("</a:accent1>")
                text = text[:a1] + '<a:accent1><a:srgbClr val="%s"/>' % ACCENT + text[end:]
                blob = text.encode("utf-8")
            dst.writestr(item, blob)
    return out.getvalue()


if __name__ == "__main__":
    with open(sys.argv[1] if len(sys.argv) > 1 else "company_template.pptx", "wb") as fh:
        fh.write(build())
