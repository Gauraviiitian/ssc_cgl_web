from __future__ import annotations

import os
from datetime import date

from fpdf import FPDF

LOGO_PATH = os.path.join(os.path.dirname(__file__), "static", "prepzone_logo.png")
CHANNEL_URL = "https://t.me/PrepZone_Official"

# fpdf2's core fonts (Helvetica) only cover Latin-1. Generated question/
# explanation text can carry a handful of characters outside that range
# (currency signs, smart punctuation) — map the common ones to ASCII, then
# fall back to lossy encode/decode so a stray character never crashes the
# whole PDF build.
_UNICODE_REPLACEMENTS = {
    "₹": "Rs. ",
    "—": "-",
    "–": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
}


def _sanitize(text: str) -> str:
    for bad, good in _UNICODE_REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", errors="replace").decode("latin-1")


class _PrepZonePDF(FPDF):
    """Adds a logo + title + channel link header, and a channel-link footer,
    to every page — fpdf2 calls header()/footer() automatically on each
    add_page(), unlike a one-off draw before the content loop."""

    def __init__(self, question_date: date):
        super().__init__()
        self._question_date = question_date

    def _full_width_cell(self, h, text, font=("Helvetica", "", 10), link=""):
        self.set_x(self.l_margin)
        self.set_font(*font)
        self.cell(self.epw, h, text, align="C", link=link, new_x="LMARGIN", new_y="NEXT")

    def header(self):
        if os.path.exists(LOGO_PATH):
            self.image(LOGO_PATH, x=10, y=8, w=32)
        self.set_y(10)
        self._full_width_cell(
            8,
            _sanitize(f"Daily Current Affairs - {self._question_date.strftime('%d %b %Y')}"),
            font=("Helvetica", "B", 14),
        )
        self._full_width_cell(6, f"Join our channel: {CHANNEL_URL}", font=("Helvetica", "", 9), link=CHANNEL_URL)
        self.set_y(30)
        self.set_draw_color(200, 200, 200)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_text_color(120, 120, 120)
        self._full_width_cell(
            10,
            _sanitize(f"PrepZone · {CHANNEL_URL} · Page {self.page_no()}"),
            font=("Helvetica", "I", 8),
            link=CHANNEL_URL,
        )
        self.set_text_color(0, 0, 0)


def build_pdf(questions: list[dict], explanations: dict[int, str], question_date: date) -> bytes:
    pdf = _PrepZonePDF(question_date)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    options_by_letter = ("A", "B", "C", "D")
    for i, q in enumerate(questions, start=1):
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(0, 6, _sanitize(f"Q{i}. {q['text']}"), new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 10)
        options = [q["option_a"], q["option_b"], q["option_c"], q["option_d"]]
        for letter, text in zip(options_by_letter, options):
            marker = "  <- Correct" if letter == q["correct_option"] else ""
            pdf.multi_cell(0, 6, _sanitize(f"   {letter}. {text}{marker}"), new_x="LMARGIN", new_y="NEXT")

        explanation = explanations.get(q["id"], "").strip()
        if explanation:
            pdf.set_font("Helvetica", "I", 9)
            pdf.multi_cell(0, 5, _sanitize(f"Explanation: {explanation}"), new_x="LMARGIN", new_y="NEXT")

        pdf.ln(3)

    output = pdf.output()
    return bytes(output) if not isinstance(output, str) else output.encode("latin-1")
