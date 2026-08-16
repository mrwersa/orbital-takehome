from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from pydantic import BaseModel

# Matches the page markers services/document.py writes into extracted_text
# when a document is uploaded: "--- Page {n} ---\n" before each page's text,
# with pages joined by "\n\n". Page numbers are always read back from these
# markers, never trusted from a model.
_PAGE_MARKER_RE = re.compile(r"--- Page (\d+) ---\n")

# PDF text extraction inserts a soft hyphen or a line break (sometimes with a
# hard hyphen) mid-word at wrap points, and reflows sentences across lines
# that a human would read as continuous. None of that should defeat an exact
# quote, so it's normalized away on both sides of the comparison. This is
# whitespace/hyphenation cleanup only — not fuzzy matching.
_SOFT_HYPHEN = "\u00ad"
_WRAP_HYPHEN_RE = re.compile(r"-\s*\n\s*")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_for_match(text: str) -> str:
    text = text.replace(_SOFT_HYPHEN, "")
    text = _WRAP_HYPHEN_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _split_pages(document_text: str) -> list[tuple[int, str]]:
    parts = _PAGE_MARKER_RE.split(document_text)
    return [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts), 2)]


class Citation(BaseModel):
    quote: str
    page: int


class CitationProposal(BaseModel):
    """What a citation proposer (real or fake) hands back: candidate quotes
    and whether it judges the document to support the answer at all."""

    supported: bool
    quotes: list[str]


class CitedAnswer(BaseModel):
    content: str
    citations: list[Citation]
    answer_supported: bool


ProposeCitations = Callable[[str, str], Awaitable[CitationProposal]]


def verify_citations(document_text: str, quotes: list[str]) -> list[Citation]:
    """Check each proposed quote against document_text and return only the
    ones that actually resolve. Pure and synchronous: no model, no network.

    A quote resolves only if it is found, by exact string match (modulo
    whitespace/hyphenation normalization), inside a single page's text. Its
    page number always comes from that match, never from the caller. A quote
    that resolves on no page is dropped, not returned.
    """
    normalized_pages = [
        (page_num, _normalize_for_match(page_text)) for page_num, page_text in _split_pages(document_text)
    ]

    resolved: list[Citation] = []
    for quote in quotes:
        normalized_quote = _normalize_for_match(quote)
        if not normalized_quote:
            continue
        for page_num, normalized_page in normalized_pages:
            if normalized_quote in normalized_page:
                resolved.append(Citation(quote=quote.strip(), page=page_num))
                break

    return resolved


async def answer_with_citations(
    document_text: str,
    question: str,
    propose_citations: ProposeCitations | None = None,
) -> CitedAnswer:
    """Answer question against document_text and attach verified citations.

    propose_citations supplies the candidate quotes to verify; it defaults to
    the real citation agent, and tests can pass a fake here to stay
    deterministic and network-free.
    """
    raise NotImplementedError
