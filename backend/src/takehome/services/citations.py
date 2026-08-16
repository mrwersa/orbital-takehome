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


class VerifiedAnswer(BaseModel):
    """What checking an already-generated answer against the document
    produces: the citations worth showing, the quotes worth keeping a
    record of but never showing, and whether the document backs the
    answer at all."""

    citations: list[Citation]
    rejected_quotes: list[str]
    answer_supported: bool


ProposeCitations = Callable[[str, str, str], Awaitable[CitationProposal]]


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


async def verify_answer(
    document_text: str,
    question: str,
    answer: str,
    propose_citations: ProposeCitations | None = None,
) -> VerifiedAnswer:
    """Check an already-generated answer to question against document_text.

    This is the one place "propose, then verify, then decide support" is
    implemented — used both by answer_with_citations below (which also
    generates the answer) and by the message route (which already has one
    from streaming, and must not generate a second, possibly different,
    answer just to check it).

    question is passed to the proposer alongside the answer: judging
    "supported" from the answer text alone lets a true-but-incidental fact
    (e.g. a company registration number mentioned in passing) make an
    otherwise-unsupported answer (e.g. "the document has no VAT number")
    look supported. The proposer needs to know what was actually asked to
    tell the difference.

    propose_citations supplies the candidate quotes; it defaults to the real
    citation agent, and callers can pass a fake here to stay deterministic
    and network-free.

    A citation only ever comes from verify_citations, never from the
    proposer directly. If the proposer judges the document doesn't support
    the answer, or none of its proposed quotes actually resolve,
    answer_supported is False — that is a distinct, deliberate state, not an
    answer that merely happens to carry zero citations.

    supported=False always wins, even if the proposer also handed back
    quotes that would otherwise resolve. A chip means "the answer is here";
    attaching one to an answer the proposer itself flagged as unsupported
    would be a contradiction, which is worse than showing no citation at
    all. Those quotes are still recorded in rejected_quotes — proposed, and
    discarded — they're just never checked against the document, since
    whether they'd resolve doesn't matter once supported is False.
    """
    if propose_citations is None:
        # Local import: takehome.services.llm imports CitationProposal from
        # this module, so importing it back at module load time would
        # cycle. By the time this function runs, both modules have already
        # finished loading, so the cycle never actually happens.
        from takehome.services.llm import propose_citations as real_propose_citations

        proposer = real_propose_citations
    else:
        proposer = propose_citations

    proposal = await proposer(document_text, question, answer)

    if not proposal.supported:
        return VerifiedAnswer(
            citations=[],
            rejected_quotes=[quote.strip() for quote in proposal.quotes],
            answer_supported=False,
        )

    resolved = verify_citations(document_text, proposal.quotes)
    resolved_quotes = {citation.quote for citation in resolved}
    rejected_quotes = [
        quote.strip() for quote in proposal.quotes if quote.strip() not in resolved_quotes
    ]
    answer_supported = len(resolved) > 0

    return VerifiedAnswer(
        citations=resolved,
        rejected_quotes=rejected_quotes,
        answer_supported=answer_supported,
    )


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
    if propose_citations is None:
        # Same deferred-import reasoning as in verify_answer above.
        from takehome.services.llm import chat_with_document

        content_parts: list[str] = []
        async for chunk in chat_with_document(question, document_text, []):
            content_parts.append(chunk)
        content = "".join(content_parts)
    else:
        # A caller supplying propose_citations is opting out of the real
        # model entirely, so nothing is generated here for it to check —
        # there is no real answer to attach. Tests use this path precisely
        # to stay deterministic and offline, and only assert on citations
        # and answer_supported, not on content.
        content = ""

    verified = await verify_answer(document_text, question, content, propose_citations)

    return CitedAnswer(
        content=content,
        citations=verified.citations,
        answer_supported=verified.answer_supported,
    )
