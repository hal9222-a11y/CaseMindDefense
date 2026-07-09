from __future__ import annotations

from pathlib import Path
from shutil import which
import os

from PIL import Image
from pypdf import PdfReader
from pypdf.errors import PdfReadError
import pytesseract


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


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
            return pytesseract.image_to_string(image, lang="eng+heb").strip()
    except Exception as exc:
        raise TextExtractionError(f"OCR text extraction failed: {exc}") from exc


def _extract_pdf_text(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        page_texts = [(page.extract_text() or "") for page in reader.pages]
        return "\n".join(page_texts).strip()
    except (PdfReadError, ValueError, OSError, KeyError) as exc:
        raise TextExtractionError(f"PDF text extraction failed: {exc}") from exc


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore").strip()

    if suffix == ".pdf":
        return _extract_pdf_text(path)

    if _is_image(path):
        return _extract_image_text(path)

    return ""


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
