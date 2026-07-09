from __future__ import annotations

import logging
import re
from pathlib import Path
from shutil import which
import os

from PIL import Image
import pytesseract


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

OCR_LANGS = "eng+heb"
PDF_OCR_RENDER_SCALE = 2.0  # ~144 dpi; raise if OCR quality is poor on small print
# ponytail: sync OCR in the request path; cap pages until background indexing lands
PDF_OCR_MAX_PAGES = int(os.getenv("CASEMIND_PDF_OCR_MAX_PAGES", "50"))


logger = logging.getLogger(__name__)


class TextExtractionError(Exception):
    pass


def _configure_tesseract() -> None:
    candidates = [
        os.getenv("TESSERACT_CMD"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        which("tesseract"),
    ]

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            return


_configure_tesseract()


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def _extract_image_text(path: Path) -> str:
    try:
        with Image.open(path) as image:
            return pytesseract.image_to_string(image, lang=OCR_LANGS).strip()
    except Exception as exc:
        raise TextExtractionError(f"OCR text extraction failed: {exc}") from exc


def _ocr_pdf(path: Path) -> str:
    """Render PDF pages to images and OCR them (fallback for scanned PDFs)."""
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            page_count = len(pdf)
            if page_count > PDF_OCR_MAX_PAGES:
                logger.warning(
                    "OCR limited to first %s of %s pages: %s",
                    PDF_OCR_MAX_PAGES, page_count, path.name,
                )
            page_texts = []
            for index in range(min(page_count, PDF_OCR_MAX_PAGES)):
                image = pdf[index].render(scale=PDF_OCR_RENDER_SCALE).to_pil()
                page_texts.append(pytesseract.image_to_string(image, lang=OCR_LANGS))
            return "\n".join(page_texts).strip()
        finally:
            pdf.close()
    except Exception as exc:
        raise TextExtractionError(f"PDF OCR failed: {exc}") from exc


HEBREW_CHAR_RE = re.compile("[֐-׿]")
HEBREW_WORD_RE = re.compile("[֐-׿]{2,}")
HEBREW_FINAL_LETTERS = set("ךםןףץ")


def _looks_reversed(text: str) -> bool:
    """Detect visual-order (reversed) Hebrew via final-letter position.

    Final forms end words in logical Hebrew; if they mostly START words,
    the text layer stored the glyphs in visual order. PDF producers differ:
    Word/court systems store logical order, others (e.g. fpdf) store visual.
    """
    starts = ends = 0
    for word in HEBREW_WORD_RE.findall(text):
        if word[0] in HEBREW_FINAL_LETTERS:
            starts += 1
        if word[-1] in HEBREW_FINAL_LETTERS:
            ends += 1
    return starts > ends


def _fix_rtl_lines(text: str) -> str:
    """Restore logical order for Hebrew stored in visual (reversed) order."""
    if not _looks_reversed(text):
        return text
    from bidi.algorithm import get_display

    return "\n".join(
        get_display(line) if HEBREW_CHAR_RE.search(line) else line
        for line in text.splitlines()
    )


def _extract_pdf_text(path: Path) -> str:
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            page_texts = [page.get_textpage().get_text_bounded() for page in pdf]
        finally:
            pdf.close()
        return _fix_rtl_lines("\n".join(page_texts)).strip()
    except Exception as exc:
        raise TextExtractionError(f"PDF text extraction failed: {exc}") from exc


def extract_text(path: Path) -> tuple[str, str]:
    """Extract text from a file.

    Returns (text, method) where method is:
      "text"        - native text layer (txt / PDF with text)
      "ocr"         - Tesseract OCR (images, scanned PDFs)
      "unsupported" - importable file type with no extractor
    """
    suffix = path.suffix.lower()

    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore").strip(), "text"

    if suffix == ".pdf":
        text = _extract_pdf_text(path)
        if text:
            return text, "text"
        return _ocr_pdf(path), "ocr"

    if _is_image(path):
        return _extract_image_text(path), "ocr"

    return "", "unsupported"


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> list[str]:
    return [chunk["text"] for chunk in chunk_text_with_offsets(text, chunk_size, overlap)]


def chunk_text_with_offsets(
    text: str,
    chunk_size: int = 1200,
    overlap: int = 150,
) -> list[dict]:
    original = text or ""

    if not original.strip():
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    if overlap < 0:
        raise ValueError("overlap must be non-negative")

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: list[dict] = []
    start = 0
    length = len(original)

    while start < length:
        end = min(start + chunk_size, length)
        chunk = original[start:end]

        if chunk.strip():
            chunks.append(
                {
                    "text": chunk,
                    "start_char": start,
                    "end_char": end,
                    "source_location": f"chars:{start}-{end}",
                }
            )

        if end == length:
            break

        start = max(0, end - overlap)

    return chunks
