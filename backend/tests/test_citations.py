"""Failing tests for the citation feature, written before the implementation exists.

`takehome.services.citations` exists only as a stub — every function raises
NotImplementedError. Each test below is expected to fail with that error
until the real implementation lands.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NoReturn

import fitz  # pymupdf
import httpx
import pytest

from takehome.services.citations import CitationProposal, answer_with_citations, verify_citations

SAMPLE_PDF = (
    Path(__file__).resolve().parents[2] / "sample-docs" / "commercial-lease-100-bishopsgate.pdf"
)

_PAGE_MARKER_RE = re.compile(r"--- Page \d+ ---\n")


def _extract_document_text(pdf_path: Path) -> str:
    """Mirror the page-marker convention used when a document is uploaded

    (see takehome.services.document.upload_document), so tests exercise the
    same text shape the real feature will have to verify citations against.
    """
    doc = fitz.open(pdf_path)
    pages: list[str] = []
    for page_num in range(len(doc)):
        text = doc[page_num].get_text()  # type: ignore[union-attr]
        if text.strip():
            pages.append(f"--- Page {page_num + 1} ---\n{text}")
    doc.close()
    return "\n\n".join(pages)


def _pick_real_line(document_text: str) -> str:
    """Return a line copied verbatim from the document, guaranteed to be an
    exact substring of document_text."""
    body = _PAGE_MARKER_RE.sub("", document_text)
    for line in body.splitlines():
        stripped = line.strip()
        if len(stripped) >= 30:
            return stripped
    raise AssertionError("sample document did not yield a usable line for this test")


@pytest.fixture(scope="module")
def document_text() -> str:
    return _extract_document_text(SAMPLE_PDF)


def test_citation_absent_from_document_is_dropped(
    document_text: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verification must resolve citations by checking the stored document
    text, not by asking a model whether a quote is real. Block all outbound
    HTTP during this test so any accidental model call fails loudly rather
    than silently passing."""

    def _no_network(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError(
            "verify_citations must not make a network/model call to decide a match"
        )

    monkeypatch.setattr(httpx.Client, "send", _no_network)
    monkeypatch.setattr(httpx.AsyncClient, "send", _no_network)

    real_quote = _pick_real_line(document_text)
    fake_quote = (
        "The Tenant is hereby granted a perpetual, royalty-free licence "
        "to sublet the entire building to a travelling circus."
    )

    resolved = verify_citations(document_text, [real_quote, fake_quote])

    resolved_quotes = [citation.quote for citation in resolved]
    assert real_quote in resolved_quotes
    assert not any("travelling circus" in quote for quote in resolved_quotes)
    assert len(resolved) == 1


async def _fake_propose_real_quote(document_text: str, question: str) -> CitationProposal:
    """Stand in for the citation agent: always proposes one quote copied
    verbatim from the document, so resolution is deterministic and network-free."""
    return CitationProposal(supported=True, quotes=[_pick_real_line(document_text)])


async def _fake_propose_nothing(document_text: str, question: str) -> CitationProposal:
    """Stand in for the citation agent on an unanswerable question: proposes
    no quotes and reports the document doesn't support an answer."""
    return CitationProposal(supported=False, quotes=[])


async def test_citations_resolve_byte_for_byte_in_document(document_text: str) -> None:
    """Every citation attached to an answer the document supports must be an
    exact span of the stored document text — not a paraphrase, not a
    near-match."""
    result = await answer_with_citations(
        document_text=document_text,
        question="What is the term of the lease, and when does it commence?",
        propose_citations=_fake_propose_real_quote,
    )

    assert result.citations, "expected at least one citation for a question the lease answers"
    for citation in result.citations:
        assert citation.quote in document_text, (
            f"citation does not appear verbatim in the stored document text: {citation.quote!r}"
        )


async def test_unanswerable_question_produces_not_found(document_text: str) -> None:
    """A question the document has no basis to answer must come back flagged
    as unsupported, with no citations — not a confident-sounding guess."""
    result = await answer_with_citations(
        document_text=document_text,
        question="What is the tenant's social security number?",
        propose_citations=_fake_propose_nothing,
    )

    assert result.answer_supported is False
    assert result.citations == []
