from pathlib import Path
from shutil import which
import os
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from PIL import Image
import pytesseract

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}

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

def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    if suffix == ".pdf":
        try:
            reader = PdfReader(str(path))
            return "\\n".join(page.extract_text() or "" for page in reader.pages).strip()
        except (PdfReadError, ValueError, OSError, KeyError) as exc:
            raise TextExtractionError(f"PDF text extraction failed: {exc}") from exc
    if _is_image(path):
        return _extract_image_text(path)
    return ""

def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> list[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    chunks = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(start + chunk_size, length)
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == length:
            break
        start = max(0, end - overlap)
    return chunks

def chunk_text_with_offsets(text: str, chunk_size: int = 1200, overlap: int = 150) -> list[dict]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    chunks = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(start + chunk_size, length)
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append({"text": chunk, "start_char": start, "end_char": end, "source_location": f"chars:{start}-{end}"})
        if end == length:
            break
        start = max(0, end - overlap)
    return chunks
