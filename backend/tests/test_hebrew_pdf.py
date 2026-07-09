from pathlib import Path

import pytest

from app.services.text_service import _fix_rtl_lines, _looks_reversed, extract_text

HEBREW_SENTENCE = "העד ראה רכב לבן ליד הבית"
ARIAL = Path(r"C:\Windows\Fonts\arial.ttf")


def test_logical_hebrew_is_left_untouched():
    text = "הנאשם הגיע לבית המשפט בירושלים"
    assert not _looks_reversed(text)
    assert _fix_rtl_lines(text) == text


def test_visual_hebrew_is_detected_and_fixed():
    visual = HEBREW_SENTENCE[::-1]
    assert _looks_reversed(visual)
    assert HEBREW_SENTENCE in _fix_rtl_lines(visual)


@pytest.mark.skipif(not ARIAL.exists(), reason="needs a Hebrew-capable system font")
def test_hebrew_text_layer_pdf_extracts_in_logical_order(tmp_path):
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("arial", fname=str(ARIAL))
    pdf.set_font("arial", size=14)
    pdf.cell(text=f"{HEBREW_SENTENCE} בתאריך 2024-01-15")
    pdf_path = tmp_path / "hebrew_statement.pdf"
    pdf.output(str(pdf_path))

    text, method = extract_text(pdf_path)

    assert method == "text"
    assert HEBREW_SENTENCE in text, f"Hebrew not in logical order: {text!r}"
    assert "2024-01-15" in text
