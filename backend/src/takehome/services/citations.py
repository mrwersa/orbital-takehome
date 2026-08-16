from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel


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
    ones that actually resolve. Pure and synchronous: no model, no network."""
    raise NotImplementedError


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
