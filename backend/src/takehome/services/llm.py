from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic_ai import Agent

from takehome.config import (
    settings,  # noqa: F401 — triggers ANTHROPIC_API_KEY export  # pyright: ignore[reportUnusedImport]
)
from takehome.services.citations import CitationProposal

agent = Agent(
    "anthropic:claude-haiku-4-5-20251001",
    system_prompt=(
        "You are a helpful legal document assistant for commercial real estate lawyers. "
        "You help lawyers review and understand documents during due diligence.\n\n"
        "IMPORTANT INSTRUCTIONS:\n"
        "- Answer questions based on the document content provided.\n"
        "- When referencing specific parts of the document, cite the relevant section or clause.\n"
        "- If the answer is not in the document, say so clearly. Do not fabricate information.\n"
        "- Be concise and precise. Lawyers value accuracy over verbosity.\n"
        "- When you reference specific content, mention the section, clause, or page."
    ),
)

# Separate agent, separate concern: given an answer already produced by `agent`
# above, decide whether the document backs it up and which exact quotes do.
# Structured output_type guarantees the shape instead of parsing free text.
citation_agent = Agent(
    "anthropic:claude-haiku-4-5-20251001",
    output_type=CitationProposal,
    system_prompt=(
        "You check whether a document actually contains the SPECIFIC "
        "information a question asked for. You will be given the full text "
        "of the document, the question that was asked, and the answer that "
        "was given.\n\n"
        "Judge 'supported' strictly against what the question specifically "
        "asked for — not against whether some sentence in the answer "
        "happens to be true and quotable. A fact mentioned in passing does "
        "not make an otherwise-unsupported answer supported.\n\n"
        "Example of what NOT to do: Question: 'What is the tenant's VAT "
        "number?' Answer: 'The VAT number is not in the document. The "
        "tenant's company registration number is OC412987.' The "
        "registration number is genuinely in the document and quoted "
        "accurately — but the question asked about a VAT number, which is "
        "NOT in the document. The correct output here is supported=false "
        "with no quotes. A different, unrelated identifier being present "
        "does not count as support, no matter how accurately it's quoted.\n\n"
        "- If the document contains the specific information the question "
        "asked for, set supported to true and extract the quotes that "
        "provide it, copied EXACTLY as they appear in the document — same "
        "words, same order, same punctuation. Do not paraphrase, "
        "summarize, correct, or shorten a quote.\n"
        "- If the document does not contain the specific information "
        "asked for, set supported to false and return no quotes — even if "
        "the answer mentions other, related facts from the document.\n"
        "- Only quote text that is actually present in the document."
    ),
)


async def propose_citations(document_text: str, question: str, answer: str) -> CitationProposal:
    """Ask citation_agent whether document_text supports answer to question."""
    prompt = (
        "<document>\n"
        f"{document_text}\n"
        "</document>\n\n"
        f"<question>\n{question}\n</question>\n\n"
        f"<answer>\n{answer}\n</answer>\n\n"
        "Does the document support this answer to the question? "
        "List the exact quotes that support it."
    )
    result = await citation_agent.run(prompt)
    return result.output


async def generate_title(user_message: str) -> str:
    """Generate a 3-5 word conversation title from the first user message."""
    result = await agent.run(
        f"Generate a concise 3-5 word title for a conversation that starts with: '{user_message}'. "
        "Return only the title, nothing else."
    )
    title = str(result.output).strip().strip('"').strip("'")
    # Truncate if too long
    if len(title) > 100:
        title = title[:97] + "..."
    return title


async def chat_with_document(
    user_message: str,
    document_text: str | None,
    conversation_history: list[dict[str, str]],
) -> AsyncIterator[str]:
    """Stream a response to the user's message, yielding text chunks.

    Builds a prompt that includes document context and conversation history,
    then streams the response from the LLM.
    """
    # Build the full prompt with context
    prompt_parts: list[str] = []

    # Add document context if available
    if document_text:
        prompt_parts.append(
            "The following is the content of the document being discussed:\n\n"
            "<document>\n"
            f"{document_text}\n"
            "</document>\n"
        )
    else:
        prompt_parts.append(
            "No document has been uploaded yet. If the user asks about a document, "
            "let them know they need to upload one first.\n"
        )

    # Add conversation history
    if conversation_history:
        prompt_parts.append("Previous conversation:\n")
        for msg in conversation_history:
            role = msg["role"]
            content = msg["content"]
            if role == "user":
                prompt_parts.append(f"User: {content}\n")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}\n")
        prompt_parts.append("\n")

    # Add the current user message
    prompt_parts.append(f"User: {user_message}")

    full_prompt = "\n".join(prompt_parts)

    async with agent.run_stream(full_prompt) as result:
        async for text in result.stream_text(delta=True):
            yield text
