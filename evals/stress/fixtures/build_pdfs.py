"""Generate calibrated synthetic PDF attachments for stress evals.

Targets are **extracted plain-text character counts** (what ``pypdf`` yields and
``MAX_ATTACHMENT_CHARS`` truncates), not binary file size on disk.

Calibration points::

    0 KB   — no attachment (baseline; no file emitted)
    5 KB   — ~5_000 chars, ~2 pages  → attach_5kb.pdf
    20 KB  — ~20_000 chars, ~8 pages  → attach_20kb.pdf
    50 KB  — ~50_000 chars, ~20 pages → attach_50kb.pdf
    100 KB — ~60_000 chars (near cap) → attach_100kb.pdf

Usage::

    uv run python evals/stress/fixtures/build_pdfs.py
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate

MAX_ATTACHMENT_CHARS = 60_000
OUTPUT_DIR = Path(__file__).resolve().parent / "pdfs"

# ponytail: binary search on paragraph count; four fixtures keeps rebuild cost acceptable.
_PARAGRAPH = (
    "Functional requirement FR-{n}: The system shall validate user input on the server "
    "before persisting records to PostgreSQL. Authentication uses OAuth2 with Google "
    "Workspace SSO. Rate limiting applies at 100 requests per minute per organisation. "
    "Audit logs retain entries for ninety days. Error responses follow RFC 7807. "
)


@dataclass(frozen=True)
class PdfTarget:
    label: str
    filename: str | None
    target_chars: int
    approx_pages: int | None


TARGETS: tuple[PdfTarget, ...] = (
    PdfTarget("0 KB (baseline)", None, 0, None),
    PdfTarget("5 KB", "attach_5kb.pdf", 5_000, 2),
    PdfTarget("20 KB", "attach_20kb.pdf", 20_000, 8),
    PdfTarget("50 KB", "attach_50kb.pdf", 50_000, 20),
    PdfTarget("100 KB", "attach_100kb.pdf", MAX_ATTACHMENT_CHARS, None),
)


def _extract_text(content: bytes) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(content))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text)
    return "\n\n".join(parts), len(reader.pages)


def _build_pdf(num_paragraphs: int) -> bytes:
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=11,
        leading=16,
        spaceAfter=6,
    )
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=72,
        rightMargin=72,
        topMargin=72,
        bottomMargin=72,
    )
    story = [Paragraph(_PARAGRAPH.format(n=i), body) for i in range(1, num_paragraphs + 1)]
    doc.build(story)
    return buffer.getvalue()


def _calibrate_paragraphs(target_chars: int, *, tolerance: int = 150) -> int:
    if target_chars <= 0:
        return 0

    low, high = 1, max(4, (target_chars // 300) + 4)
    while len(_extract_text(_build_pdf(high))[0]) < target_chars:
        high *= 2

    best = high
    best_delta = abs(len(_extract_text(_build_pdf(high))[0]) - target_chars)
    while low <= high:
        mid = (low + high) // 2
        chars = len(_extract_text(_build_pdf(mid))[0])
        delta = abs(chars - target_chars)
        if delta < best_delta:
            best, best_delta = mid, delta
        if chars < target_chars:
            low = mid + 1
        else:
            high = mid - 1

    while best_delta > tolerance:
        candidate = best + (1 if len(_extract_text(_build_pdf(best))[0]) < target_chars else -1)
        if candidate < 1:
            break
        chars = len(_extract_text(_build_pdf(candidate))[0])
        delta = abs(chars - target_chars)
        if delta >= best_delta:
            break
        best, best_delta = candidate, delta

    return best


def build_target(target: PdfTarget) -> bytes | None:
    if target.filename is None:
        return None
    paragraphs = _calibrate_paragraphs(target.target_chars)
    return _build_pdf(paragraphs)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Writing PDFs to {OUTPUT_DIR}\n")
    print(f"{'label':<22} {'file':<20} {'bytes':>8} {'chars':>8} {'pages':>6}")
    print("-" * 68)

    for target in TARGETS:
        if target.filename is None:
            print(f"{target.label:<22} {'(none)':<20} {'—':>8} {'—':>8} {'—':>6}")
            continue

        content = build_target(target)
        assert content is not None
        path = OUTPUT_DIR / target.filename
        path.write_bytes(content)
        text, pages = _extract_text(content)
        print(
            f"{target.label:<22} {target.filename:<20} "
            f"{len(content):>8,} {len(text):>8,} {pages:>6}"
        )

    print(
        f"\n100 KB fixture targets MAX_ATTACHMENT_CHARS={MAX_ATTACHMENT_CHARS:,} "
        f"(extracted chars, not file size)."
    )


if __name__ == "__main__":
    main()
