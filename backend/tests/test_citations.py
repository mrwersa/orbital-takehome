"""Failing tests for the citation feature, written before the implementation exists.

`takehome.services.citations` exists only as a stub — every function raises
NotImplementedError. Each test below is expected to fail with that error
until the real implementation lands.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NoReturn, cast

import fitz  # pyright: ignore[reportMissingTypeStubs] — PyMuPDF ships no stubs
import httpx
import pytest

from takehome.services.citations import (
    CitationProposal,
    answer_with_citations,
    verify_answer,
    verify_citations,
)

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
        text = cast(str, doc[page_num].get_text())  # type: ignore[union-attr]
        if text.strip():
            pages.append(f"--- Page {page_num + 1} ---\n{text}")
    doc.close()
    return "\n\n".join(pages)


def _pick_real_lines(document_text: str, count: int) -> list[str]:
    """Return `count` distinct lines copied verbatim from the document,
    each guaranteed to be an exact substring of document_text."""
    body = _PAGE_MARKER_RE.sub("", document_text)
    lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if len(stripped) >= 30 and stripped not in lines:
            lines.append(stripped)
            if len(lines) == count:
                return lines
    raise AssertionError(f"sample document did not yield {count} usable lines for this test")


def _pick_real_line(document_text: str) -> str:
    """Return a line copied verbatim from the document, guaranteed to be an
    exact substring of document_text."""
    return _pick_real_lines(document_text, 1)[0]


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


async def _fake_propose_real_quote(
    document_text: str, question: str, answer: str
) -> CitationProposal:
    """Stand in for the citation agent: always proposes one quote copied
    verbatim from the document, so resolution is deterministic and network-free."""
    return CitationProposal(supported=True, quotes=[_pick_real_line(document_text)])


async def _fake_propose_nothing(
    document_text: str, question: str, answer: str
) -> CitationProposal:
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


async def test_unsupported_answer_returns_no_citations_even_if_a_quote_resolves(
    document_text: str,
) -> None:
    """Regression: asked for the tenant's VAT number, the model correctly
    said the document doesn't contain it (supported=False) but proposed a
    quote from page 3 anyway. A chip means "the answer is here" — attaching
    one to an answer the proposer itself flagged as unsupported is a
    contradiction, and that's worse than no citation at all. supported=False
    must always win, even when the quote it came with would otherwise
    resolve. The quote is still kept in rejected_quotes for the record.
    """
    real_quote = _pick_real_line(document_text)

    async def fake_propose_unsupported_but_quoted(
        document_text: str, question: str, answer: str
    ) -> CitationProposal:
        return CitationProposal(supported=False, quotes=[real_quote])

    result = await verify_answer(
        document_text,
        "What is the tenant's VAT number?",
        "The document does not contain the tenant's VAT number.",
        propose_citations=fake_propose_unsupported_but_quoted,
    )

    assert result.answer_supported is False
    assert result.citations == []
    assert result.rejected_quotes == [real_quote]


async def test_citation_proposer_receives_the_original_question(document_text: str) -> None:
    """Regression: asked for the tenant's VAT registration number, the chat
    agent correctly answered that the document doesn't contain it — but also
    mentioned, in passing, the Tenant's company registration number, which
    genuinely is in the document. The citation agent, seeing only the answer
    text, judged the whole answer "supported" because that incidental fact
    checks out — it had no way to know the actual question was about a VAT
    number specifically, not a company registration number.

    The fix is for the proposer to receive the original question alongside
    the answer, so it can judge support against what was actually asked. This
    test locks in that the question reaches the proposer at all; it can't
    unit-test the real model's judgment, only that the wiring carries the
    question through answer_with_citations -> verify_answer -> the proposer
    call, instead of silently dropping it as it did before.
    """
    received: dict[str, str] = {}

    async def recording_propose_citations(
        document_text: str, question: str, answer: str
    ) -> CitationProposal:
        received["question"] = question
        return CitationProposal(supported=False, quotes=[])

    question = "What is the tenant's VAT registration number?"
    result = await answer_with_citations(
        document_text=document_text,
        question=question,
        propose_citations=recording_propose_citations,
    )

    assert received["question"] == question
    assert result.answer_supported is False


async def test_partial_resolution_shows_the_quotes_that_resolve(document_text: str) -> None:
    """The proposer says supported=true and hands back three quotes; two are
    real lines from the document, one is fabricated. Partial grounding is a
    documented, accepted limitation (see DECISIONS.md) rather than something
    this function can detect or prevent — it only ever checks quotes it was
    actually given, and a proposer that silently omits a quote for some
    other claim is invisible to it either way. Given that, withholding the
    quotes that DO resolve doesn't close that gap, it just throws away
    correct citations — so a partial resolve shows exactly what resolved
    and records the rest as rejected.
    """
    real_quote_1, real_quote_2 = _pick_real_lines(document_text, 2)
    fake_quote = (
        "The Landlord irrevocably waives all rights to inspect the Premises "
        "for the remainder of the Term."
    )

    async def fake_propose_partial_match(
        document_text: str, question: str, answer: str
    ) -> CitationProposal:
        return CitationProposal(supported=True, quotes=[real_quote_1, fake_quote, real_quote_2])

    result = await verify_answer(
        document_text,
        "Summarise the key terms of the lease.",
        "Some real terms, and one fabricated one.",
        propose_citations=fake_propose_partial_match,
    )

    assert result.answer_supported is True
    assert {citation.quote for citation in result.citations} == {real_quote_1, real_quote_2}
    assert result.rejected_quotes == [fake_quote]
    assert result.proposed_count == 3
    assert result.resolved_count == 2


def test_citations_carry_the_clause_they_come_from(document_text: str) -> None:
    """Regression: a citation must carry the clause/sub-clause number it was
    quoted from (e.g. "8.3.1"), read from the document's own layout, not
    just its page. Finds a real numbered sub-clause line in the sample
    lease rather than hardcoding one, so this doesn't quietly stop testing
    anything if the sample document changes.
    """
    body = _PAGE_MARKER_RE.sub("", document_text)
    clause_line_re = re.compile(r"^(\d+(?:\.\d+){1,3})\s+(.{30,})$", re.MULTILINE)
    match = clause_line_re.search(body)
    assert match is not None, "sample document did not yield a numbered sub-clause for this test"
    expected_clause = match.group(1)
    quote = match.group(2).strip()

    resolved = verify_citations(document_text, [quote])

    assert len(resolved) == 1
    assert resolved[0].clause == expected_clause


def test_clause_is_none_when_no_clause_number_precedes_the_quote(document_text: str) -> None:
    """Regression: a quote from before any clause numbering starts on its
    page -- the sample lease's title page has none at all -- must resolve
    with clause=None rather than a wrong or fabricated number."""
    # _PAGE_MARKER_RE has no capture group, so split() drops the markers:
    # pages[0] is empty (the text starts with the first marker), pages[1]
    # is page 1's own body text.
    page_one_text = _PAGE_MARKER_RE.split(document_text)[1]
    line = next(
        (
            stripped
            for stripped in (raw.strip() for raw in page_one_text.splitlines())
            if len(stripped) >= 20
        ),
        None,
    )
    assert line is not None, "sample document's page 1 did not yield a usable line for this test"

    resolved = verify_citations(document_text, [line])

    assert len(resolved) == 1
    assert resolved[0].page == 1
    assert resolved[0].clause is None
