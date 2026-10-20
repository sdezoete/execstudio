"""Builds a small "existing" deck with a picture, a table and a chart, for tests and demos.

    python tests/sample_deck.py sample.pptx
"""
import io
import struct
import sys
import zlib

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches


def _png(w=320, h=180, rgb=(31, 71, 201)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def build():
    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[0])
    s1.shapes.title.text = "Quarterly operations review"
    s1.placeholders[1].text = "Operations team"

    s2 = prs.slides.add_slide(prs.slide_layouts[1])
    s2.shapes.title.text = "Overview of customer service"
    body = s2.placeholders[1].text_frame
    body.text = "Average handling time went down from 7.2 to 6.1 minutes over the quarter"
    for t in ["First contact resolution improved to 78%", "Staffing was below plan in August",
              "Customer satisfaction stable at 4.3", "New ticketing tool live in two sites",
              "Training completed for 85% of agents", "Backlog cleared by mid-September"]:
        body.add_paragraph().text = t
    s2.notes_slide.notes_text_frame.text = "Mention the August staffing gap."

    s3 = prs.slides.add_slide(prs.slide_layouts[5])
    s3.shapes.title.text = "Ticket volumes"
    cd = CategoryChartData()
    cd.categories = ["Jul", "Aug", "Sep"]
    cd.add_series("Tickets", (1200, 1350, 1100))
    s3.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(1.8), Inches(5), Inches(4), cd)
    s3.shapes.add_picture(io.BytesIO(_png()), Inches(6.3), Inches(2), Inches(3.2))

    s4 = prs.slides.add_slide(prs.slide_layouts[5])
    s4.shapes.title.text = "Site comparison"
    tbl = s4.shapes.add_table(3, 3, Inches(1), Inches(2), Inches(8), Inches(1.5)).table
    for r, row in enumerate([["Site", "AHT", "FCR"], ["Riyadh", "5.9", "80%"], ["Dammam", "6.4", "75%"]]):
        for c, v in enumerate(row):
            tbl.cell(r, c).text = v
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


if __name__ == "__main__":
    with open(sys.argv[1] if len(sys.argv) > 1 else "sample.pptx", "wb") as fh:
        fh.write(build())
