"""OCR: text extraction from a receipt photo or PDF, behind a Protocol.

The real engine (Tesseract for images, pypdf for PDFs) needs a system binary:
it is never imported at module load, so the node runs and the tests pass
without it. The pipeline only ever sees an `OcrEngine`, which a test replaces
with a fake returning fixed text — the same "substitute with a finto" rule as
`LedgerClient` and `MerchantStore`.

Receipt PDFs are usually digital (text already there): pypdf extracts it with
no OCR. Photo receipts go through Tesseract with a light preprocessing step
(grayscale + autocontrast) which makes the Italian output much more reliable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class OcrError(RuntimeError):
    """The document could not be turned into text (engine missing / unreadable)."""


class OcrEngine(Protocol):
    def extract_text(self, path: str | Path) -> str:
        """Return the plain text of an image or PDF document."""
        ...


def extract_pdf_text(path: str | Path) -> str:
    """Plain text of a (digital) PDF via pypdf — no OCR, no external binary."""
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover - dependency always installed
        raise OcrError("pypdf non installato") from e
    try:
        reader = PdfReader(str(path))
    except Exception as e:  # noqa: BLE001 - a bad PDF is the caller's problem
        raise OcrError(f"PDF non leggibile: {e}") from e
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _ocr_image(path: Path, *, lang: str) -> str:
    """OCR a raster image with Tesseract. Imports stay here: tesseract may be absent."""
    try:
        import pytesseract
        from PIL import Image, ImageOps
    except ImportError as e:  # pragma: no cover - dependency always installed
        raise OcrError("pytesseract/Pillow non installati") from e
    try:
        img = Image.open(path)
    except Exception as e:  # noqa: BLE001
        raise OcrError(f"immagine non leggibile: {e}") from e
    gray = ImageOps.autocontrast(ImageOps.grayscale(img))
    try:
        return pytesseract.image_to_string(gray, lang=lang)
    except Exception as e:  # noqa: BLE001 - TesseractNotFoundError and friends
        raise OcrError(f"OCR non riuscito (tesseract installato?): {e}") from e


class TesseractOcr:
    """Real engine: pypdf for PDFs, Tesseract for raster images."""

    def __init__(self, *, lang: str = "ita") -> None:
        self.lang = lang

    def extract_text(self, path: str | Path) -> str:
        p = Path(path)
        suffix = p.suffix.lower()
        if suffix == ".pdf":
            return extract_pdf_text(p)
        return _ocr_image(p, lang=self.lang)
