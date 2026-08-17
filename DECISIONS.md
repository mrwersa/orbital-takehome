# Decisions

## Partial grounding is a documented, accepted limitation

An answer can make several distinct factual claims. The citation agent
proposes quotes for what it chooses to check, and `verify_citations`
confirms whether each proposed quote is genuinely in the document. That
resolver is airtight for what it's given: a quote that isn't in the
document text, exactly, never becomes a citation. But it can only ever
verify quotes it's given. If the agent proposes a quote for one claim and
silently gives no quote at all for a second, fabricated claim in the same
answer, nothing in this pipeline can detect the second claim exists. One
real citation shows up, the answer reads as supported, and the fabricated
claim rides along uncited.

We tried closing this at the prompt layer: an instruction telling the
citation agent that every distinct claim in the answer needs its own
quote, and requiring every proposed quote to resolve before showing any of
them (all-or-nothing) rather than showing whatever happened to resolve.
It didn't close the gap — an agent that omits a quote for a fabricated
claim sails through an all-or-nothing check exactly as easily as a partial
one, since there's nothing in the check that can see a claim it was never
told about. What the stricter check actually did was cost real, correct
citations whenever the agent's own quote selection was merely incomplete,
not wrong: with the prompt change live, I ran one previously-reliable
question ("What is the length of the Term of this lease, and who are the
Landlord and Tenant?") against the real model four times in immediate
succession. Three came back supported, with 4, 3, and 5 citations
respectively — a count that shouldn't vary at all for an identical,
unchanging document and question. The fourth came back
`answer_supported=false` with zero citations, for the same question the
model had just answered correctly and completely three other times.
That's a worse failure than the one the check was meant to prevent, so it
was reverted. (That specific question had two clean prior runs earlier in
this session, not ten — the "reliable beforehand" claim rests on those
four back-to-back runs showing 3-true-1-false on their own, not on a
longer track record. A different question, run ten times through
`scripts/eval.sh`, did show 10/10 consistent citations — but that was
before the prompt change existed, and it was never re-run against the
modified prompt to see whether it also regressed.) Current behavior: a
partial resolve shows the quotes that do resolve and records the rest as
rejected; `answer_supported` is true whenever at least one proposed quote
resolves, same as before either attempt.

**What I'd build next:** the citation agent needs to judge and report
support per claim, not one `supported` boolean for the whole answer.
Concretely — the agent identifies each distinct factual claim in the
answer and, for each one, either a supporting quote or an explicit
"no support found" marker; `answer_supported` becomes true only when
every claim has a quote, and any claim without one either gets flagged
to the user or drops the whole answer to unsupported, deliberately. That
turns "the agent silently didn't mention it" into "the agent explicitly
said this claim has no support" — the first is invisible to any
downstream check, the second isn't.

This is a real redesign, not a patch: a new proposal schema (claims, not
just quotes), a new `Message.citations`-equivalent persisted shape (or a
migration to extend the current one), a materially different prompt, and
UI to show per-claim status rather than a flat citation list. Out of
scope for this pass — too large to verify before submitting this
take-home. Left here as the next real piece of work on this feature.
