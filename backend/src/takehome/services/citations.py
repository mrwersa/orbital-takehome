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


# A clause/sub-clause label ("1.1", "8.3.1", ...) at the start of its own
# line. Confirmed against the sample lease: real labels always open a line
# ("8.3.1 The Tenant's right..."); a cross-reference to another clause
# mid-sentence ("in accordance with clause 8.2.") never does. Anchoring on
# line start is what keeps this from picking up the wrong number.
#
# The dot is required, not optional: a bare integer opening a line is far
# more likely to be something else entirely -- the sample lease itself has
# "14 Bedford Row, London WC1R 4ED" as a standalone line on its cover page,
# which a bare-digit pattern reads as "clause 14" on a page with no clauses
# at all. Real sub-clause numbering in this kind of document is reliably
# dotted ("1.1", "8.3.1"); a top-level, undotted clause is conventionally
# spelled out ("Section 8"), not printed as a lone digit. Showing no clause
# number is better than showing a wrong one, same as a quote that can't be
# verified is dropped rather than guessed at.
_CLAUSE_LABEL_RE = re.compile(r"(?m)^(\d+(?:\.\d+){1,3})\s")


def _find_original_position(page_text: str, quote: str) -> int | None:
    """Best-effort: locate quote inside page_text's ORIGINAL (non-normalized)
    layout, tolerating whitespace differences but not the soft-hyphen/
    wrap-hyphen artifacts _normalize_for_match handles. Only used to find
    roughly where to start looking for a clause label — if it fails, the
    citation still resolves and is still shown, just without a clause
    number, rather than guessing at one.
    """
    words = quote.strip().split()
    if not words:
        return None
    pattern = r"\s+".join(re.escape(word) for word in words)
    match = re.search(pattern, page_text)
    return match.start() if match else None


def _find_clause_number(page_text: str, quote: str) -> str | None:
    """The nearest clause/sub-clause label appearing before quote on its
    page, or None if quote's position can't be found or nothing precedes
    it. Read from the document's own layout, never from the model."""
    position = _find_original_position(page_text, quote)
    if position is None:
        return None

    clause: str | None = None
    for label_match in _CLAUSE_LABEL_RE.finditer(page_text):
        if label_match.start() > position:
            break
        clause = label_match.group(1)
    return clause


class Citation(BaseModel):
    quote: str
    page: int
    clause: str | None = None


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
    answer at all.

    proposed_count and resolved_count are the raw exact-match numbers —
    how many quotes the proposer offered and how many of those actually
    resolved against the document text. They exist so a caller
    logging/measuring resolution rate gets the true text-matching result,
    independent of which of those resolved quotes end up in citations.
    """

    citations: list[Citation]
    rejected_quotes: list[str]
    answer_supported: bool
    proposed_count: int
    resolved_count: int


ProposeCitations = Callable[[str, str, str], Awaitable[CitationProposal]]


def verify_citations(document_text: str, quotes: list[str]) -> list[Citation]:
    """Check each proposed quote against document_text and return only the
    ones that actually resolve. Pure and synchronous: no model, no network.

    A quote resolves only if it is found, by exact string match (modulo
    whitespace/hyphenation normalization), inside a single page's text. Its
    page number always comes from that match, never from the caller. A quote
    that resolves on no page is dropped, not returned.

    Its clause number, if any, is read from the same page's original text —
    the nearest clause/sub-clause label preceding the quote — and is best
    effort: a quote that can't be located in the original layout (see
    _find_original_position) resolves with clause=None rather than a guess.
    """
    pages = [
        (page_num, page_text, _normalize_for_match(page_text))
        for page_num, page_text in _split_pages(document_text)
    ]

    resolved: list[Citation] = []
    for quote in quotes:
        normalized_quote = _normalize_for_match(quote)
        if not normalized_quote:
            continue
        for page_num, page_text, normalized_page in pages:
            if normalized_quote in normalized_page:
                clause = _find_clause_number(page_text, quote)
                resolved.append(Citation(quote=quote.strip(), page=page_num, clause=clause))
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
    proposer directly. answer_supported is True only when the proposer said
    the document supports the answer AND at least one of its proposed
    quotes actually resolves — that is a distinct, deliberate state, not an
    answer that merely happens to carry zero citations.

    supported=False always wins, even if the proposer also handed back
    quotes that would otherwise resolve. A chip means "the answer is here";
    attaching one to an answer the proposer itself flagged as unsupported
    would be a contradiction, which is worse than showing no citation at
    all. Those quotes are still recorded in rejected_quotes — proposed, and
    discarded — they're just never checked against the document, since
    whether they'd resolve doesn't matter once supported is False.

    A partial resolve (some proposed quotes match, some don't) shows the
    ones that do and records the rest as rejected. This is not a guarantee
    that every claim in the answer has evidence — the proposer can omit a
    quote for a claim entirely, and nothing here can detect that, since
    verification only ever checks quotes it was actually given. An earlier
    version of this function required every proposed quote to resolve
    before showing any of them, specifically to close that gap — it didn't:
    the proposer omitting a quote for a fabricated claim sails through an
    all-or-nothing check exactly as easily as a partial one, since there's
    nothing to detect. What the stricter check actually did was cost real,
    correct citations whenever the proposer's own quote selection was
    merely incomplete (confirmed live: a fully-supported, previously
    reliable multi-claim answer started intermittently coming back with no
    citations at all). Closing the real gap needs the proposer to judge and
    report support per claim, not one bool for the whole answer — see
    DECISIONS.md.
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

    resolved = verify_citations(document_text, proposal.quotes)
    proposed_count = len(proposal.quotes)
    resolved_count = len(resolved)

    if not proposal.supported or resolved_count == 0:
        return VerifiedAnswer(
            citations=[],
            rejected_quotes=[quote.strip() for quote in proposal.quotes],
            answer_supported=False,
            proposed_count=proposed_count,
            resolved_count=resolved_count,
        )

    resolved_quotes = {citation.quote for citation in resolved}
    rejected_quotes = [
        quote.strip() for quote in proposal.quotes if quote.strip() not in resolved_quotes
    ]

    return VerifiedAnswer(
        citations=resolved,
        rejected_quotes=rejected_quotes,
        answer_supported=True,
        proposed_count=proposed_count,
        resolved_count=resolved_count,
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
