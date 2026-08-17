from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from takehome.db.models import Message
from takehome.db.session import get_session
from takehome.services.citations import Citation, verify_answer
from takehome.services.conversation import get_conversation, update_conversation
from takehome.services.document import get_document_for_conversation
from takehome.services.llm import chat_with_document, generate_title

logger = structlog.get_logger()

router = APIRouter(tags=["messages"])

# Bounds how long the SSE stream will wait on citation verification after
# the answer has finished generating. Real calls take a few seconds; this
# is generous headroom, not a target — past it we degrade the same way an
# outright verification failure does, rather than leaving the client
# waiting on the final event indefinitely.
_CITATION_VERIFICATION_TIMEOUT_SECONDS: float = 30.0


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    sources_cited: int
    citations: list[Citation] = []
    answer_supported: bool | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageCreate(BaseModel):
    content: str


async def _verify_and_persist_citations(
    message_id: str,
    document_text: str | None,
    question: str,
    full_response: str,
    conversation_id: str,
) -> Message:
    """Verify citations against document_text and persist the result onto
    the already-saved message row, then return the updated row.

    document_text is None when there is nothing to verify (no document, or
    the answer is our own canned error message) — the caller decides that
    once, before calling this, and reuses the same decision to emit the
    "verifying" SSE event. Two separate copies of that condition would risk
    telling the client a check is starting and then not running one.

    Callers must run this via asyncio.shield. If the client disconnects
    while this is in flight, the SSE generator awaiting it gets cancelled —
    but asyncio.CancelledError is not an Exception, so a plain try/except
    around the awaiting code would NOT stop that cancellation from also
    aborting this function before it reaches the update below, leaving the
    message stuck at answer_supported=None (looking exactly like an
    ordinary, unchecked answer) forever, with nothing left to ever finish
    the job. Shielding this call lets it keep running to completion in the
    background even when nothing is left listening for its result.
    """
    citations: list[Citation] = []
    rejected_quotes: list[str] = []
    answer_supported: bool | None = None

    if document_text is not None:
        try:
            verified = await asyncio.wait_for(
                verify_answer(document_text, question, full_response),
                timeout=_CITATION_VERIFICATION_TIMEOUT_SECONDS,
            )
            citations = verified.citations
            rejected_quotes = verified.rejected_quotes
            answer_supported = verified.answer_supported
            # proposed/resolved/dropped are the raw exact-match numbers,
            # not len(citations)/len(rejected_quotes) — a partial resolve
            # (say 1 of 2 quotes) still shows zero citations and records
            # both quotes as rejected (nothing shown), but only one of
            # them actually failed to match the document text. Logging
            # len(rejected_quotes) here would report that as 0 resolved,
            # 2 dropped instead of the true 1 resolved, 1 dropped.
            logger.info(
                "Citations verified",
                conversation_id=conversation_id,
                proposed=verified.proposed_count,
                resolved=verified.resolved_count,
                dropped=verified.proposed_count - verified.resolved_count,
            )
        except Exception:
            # Covers a real failure and a timeout alike. Either way we
            # couldn't verify this answer — that's a distinct state from
            # "nothing needed verifying" (the no-document/canned-error
            # cases, which leave answer_supported as None) and must not
            # render as an ordinary, trustworthy answer just because
            # verification didn't get to run.
            logger.exception(
                "Failed to verify citations",
                conversation_id=conversation_id,
            )
            answer_supported = False

    from takehome.db.session import async_session as session_factory

    async with session_factory() as update_session:
        result = await update_session.execute(select(Message).where(Message.id == message_id))
        assistant_message = result.scalar_one()
        assistant_message.sources_cited = len(citations)
        assistant_message.citations = [c.model_dump() for c in citations]
        assistant_message.rejected_quotes = rejected_quotes
        assistant_message.answer_supported = answer_supported
        await update_session.commit()
        await update_session.refresh(assistant_message)
        return assistant_message


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@router.get(
    "/api/conversations/{conversation_id}/messages",
    response_model=list[MessageOut],
)
async def list_messages(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    """List all messages in a conversation, ordered by creation time."""
    # Verify the conversation exists
    conversation = await get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    result = await session.execute(stmt)
    messages = list(result.scalars().all())

    return [
        MessageOut(
            id=m.id,
            conversation_id=m.conversation_id,
            role=m.role,
            content=m.content,
            sources_cited=m.sources_cited,
            citations=[Citation.model_validate(c) for c in m.citations],
            answer_supported=m.answer_supported,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post("/api/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: MessageCreate,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Send a user message and stream back the AI response via SSE."""
    # Verify the conversation exists
    conversation = await get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Save the user message
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=body.content,
    )
    session.add(user_message)
    await session.commit()
    await session.refresh(user_message)

    logger.info("User message saved", conversation_id=conversation_id, message_id=user_message.id)

    # Load document text for the conversation
    document = await get_document_for_conversation(session, conversation_id)
    document_text: str | None = document.extracted_text if document else None

    # Load conversation history (exclude the message we just saved, it will be the user_message param)
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.id != user_message.id)
        .order_by(Message.created_at.asc())
    )
    result = await session.execute(stmt)
    history_messages = list(result.scalars().all())

    conversation_history: list[dict[str, str]] = [
        {"role": m.role, "content": m.content} for m in history_messages
    ]

    # Determine if this is the first user message (for title generation)
    user_msg_count = sum(1 for m in history_messages if m.role == "user")
    is_first_message = user_msg_count == 0

    async def event_stream() -> AsyncIterator[str]:
        """Generate SSE events with the streamed LLM response."""
        full_response = ""
        had_error = False

        try:
            async for chunk in chat_with_document(
                user_message=body.content,
                document_text=document_text,
                conversation_history=conversation_history,
            ):
                full_response += chunk
                event_data = json.dumps({"type": "content", "content": chunk})
                yield f"data: {event_data}\n\n"

        except Exception:
            logger.exception(
                "Error during LLM streaming",
                conversation_id=conversation_id,
            )
            had_error = True
            error_msg = "I'm sorry, an error occurred while generating a response. Please try again."
            full_response = error_msg
            event_data = json.dumps({"type": "content", "content": error_msg})
            yield f"data: {event_data}\n\n"

        # Save the assistant message immediately, before citation
        # verification, so a slow or hung verification call — or a client
        # disconnecting while it's in flight — can't lose an answer that
        # already finished streaming and was already shown to the user.
        # Citation fields start empty/unknown and are filled in below.
        from takehome.db.session import async_session as session_factory

        async with session_factory() as save_session:
            assistant_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=full_response,
                sources_cited=0,
                citations=[],
                rejected_quotes=[],
                answer_supported=None,
            )
            save_session.add(assistant_message)
            await save_session.commit()
            await save_session.refresh(assistant_message)

            # Auto-generate title from first user message
            if is_first_message:
                try:
                    title = await generate_title(body.content)
                    await update_conversation(save_session, conversation_id, title)
                    logger.info(
                        "Auto-generated conversation title",
                        conversation_id=conversation_id,
                        title=title,
                    )
                except Exception:
                    logger.exception(
                        "Failed to generate title",
                        conversation_id=conversation_id,
                    )

        message_id = assistant_message.id

        # Whether there is genuinely something to verify, decided once and
        # reused below for both the "verifying" event and the check itself
        # — see _verify_and_persist_citations' docstring for why that
        # matters. Announcing a check that then never runs would be a lie.
        text_to_verify = (
            document_text if (document_text and full_response and not had_error) else None
        )

        if text_to_verify is not None:
            verifying_data = json.dumps({"type": "verifying"})
            yield f"data: {verifying_data}\n\n"

        # Verify citations against the stored document text now that the
        # answer itself is safely persisted, shielded so a client
        # disconnect can't cancel it before the update below runs — see
        # _verify_and_persist_citations' docstring for why that matters.
        # If the client is still connected, this just behaves like a
        # normal await.
        verify_task = asyncio.ensure_future(
            _verify_and_persist_citations(
                message_id, text_to_verify, body.content, full_response, conversation_id
            )
        )
        assistant_message = await asyncio.shield(verify_task)

        # Send the final message event with the complete assistant message.
        # rejected_quotes is persisted (in _verify_and_persist_citations)
        # but deliberately never goes out over the wire — it's a record of
        # what we rejected, not something the UI shows.
        message_data = json.dumps(
            {
                "type": "message",
                "message": {
                    "id": assistant_message.id,
                    "conversation_id": assistant_message.conversation_id,
                    "role": assistant_message.role,
                    "content": assistant_message.content,
                    "sources_cited": assistant_message.sources_cited,
                    "citations": assistant_message.citations,
                    "answer_supported": assistant_message.answer_supported,
                    "created_at": assistant_message.created_at.isoformat(),
                },
            }
        )
        yield f"data: {message_data}\n\n"

        # Send the done signal
        done_data = json.dumps(
            {
                "type": "done",
                "sources_cited": assistant_message.sources_cited,
                "message_id": assistant_message.id,
            }
        )
        yield f"data: {done_data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
