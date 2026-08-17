# Working agreement

## How this repo runs

Everything is in Docker Compose, driven by `just`. Containers must be up
before any check: `just dev-detach`. Never run `just dev`, it blocks.
`just check` is ruff plus pyright plus biome. `just test` is pytest, and it
only exists because I added it.

## Verify before claiming done

Run `just check` and `just test`. Paste the output. Never say a change works
without it. **pyright runs in strict mode**: annotate every parameter and
return, no implicit Any, or check goes red.

## You may change without asking

Frontend components under frontend/src/components, styling, the citation and
LLM service code under backend/src/takehome/services, tests, and anything
you have added yourself.

## Bring back to me first

Alembic migrations, the document parsing path in services/document.py, the
SSE event shape in routers/messages.py, and any new dependency. Blast radius
is larger than it looks here.

## Never

Rewrite features outside the citation work. Add a state management library
or a vector store. Change docker-compose.yml or the justfile beyond the test
mount and the test recipe.

## Mine, not yours

`DECISIONS.md` and `PART1.md` are mine. Do not author them, and do not add to
them unless I hand you the text. When I say something goes in `DECISIONS.md`
as an accepted limitation, that closes the topic. Do not propose an
implementation for it again.

Never invent a number. If a document has a placeholder where a measurement
goes, leave the placeholder. Eval results come from a run I watched, not from
what a plausible result would look like.

## Facts about this codebase, so you do not assume otherwise

The chat agent has no `output_type` and streams plain text. Extracted PDF
text is one column with `--- Page N ---` markers and no offsets. A citation
is only valid if its quote is found in that text by exact string match, and
one that is not found is dropped, never shown.

## House style

Match what is already there. Do not introduce a second way of doing
something that the repo already does one way.
