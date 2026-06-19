"""Extract plain text from PDF and DOCX attachments."""

from __future__ import annotations

import io
from pathlib import PurePath

from docx import Document
from pypdf import PdfReader

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx"})


class UnsupportedFileTypeError(ValueError):
    """Raised when an attachment is not a supported PDF or DOCX file."""


def extract_pdf(content: bytes) -> str:
    """Return concatenated text from all pages of a PDF."""
    reader = PdfReader(io.BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages).strip()


def extract_docx(content: bytes) -> str:
    """Return paragraph text from a DOCX file."""
    document = Document(io.BytesIO(content))
    return "\n".join(p.text for p in document.paragraphs).strip()


def extract_content(filename: str, content: bytes) -> str:
    """Dispatch extraction by file extension."""
    extension = PurePath(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(SUPPORTED_EXTENSIONS)
        raise UnsupportedFileTypeError(
            f"Unsupported file type {extension!r} for {filename!r}; "
            f"supported extensions: {supported}"
        )
    if extension == ".pdf":
        return extract_pdf(content)
    return extract_docx(content)
