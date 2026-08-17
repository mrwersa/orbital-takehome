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
was reverted.

To be exact about the evidence: that question had two clean runs earlier
in the session, not ten, so the case rests on those four back-to-back
runs on their own. The ten-run result described below is a different
question, measured before the prompt change existed and never re-run
against it.

Current behaviour: a partial resolve shows the quotes that do resolve and
records the rest as rejected; `answer_supported` is true whenever at least
one proposed quote resolves, same as before either attempt.

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

## What the eval measured

`scripts/eval.sh` runs each question ten times, each in a fresh
conversation with a fresh upload, so no run sees another's answer in its
history. Two questions: one the lease answers, one it doesn't.

**Answerable** ("when can the tenant end the lease early, and on what
conditions?"): ten runs produced three distinct citation sets, and every
citation in every run resolved against page 7 and no other page. Eight
runs quoted the same four provisions of Section 8 the same way. A ninth
quoted the same four but pulled the clause numbers and headings into the
quotes with them. The tenth quoted one provision of the four.

So the feature is stable about where the answer lives and unstable about
two separate things: where it cuts a quote, and how many of the relevant
provisions it troubles to quote at all. The second of those is the
partial-grounding limitation above, caught in the act. That tenth run
produced an answer covering four provisions with evidence attached to
one, and nothing in this pipeline can tell that the other three went
uncited — the answer arrives supported, with a citation that genuinely
resolves, and the omission is invisible. One run in ten, on the
best-behaved question I have.

**Unanswerable** ("what is the tenant's VAT registration number?"): 10/10
runs came back `answer_supported=false` with no citations, and all ten
said so in their own text as well. That second half matters, because the
original failure here was an answer that stated the document had no VAT
number while carrying a citation to page 3 — a company registration
number mentioned in passing, true in itself and irrelevant to the
question. Passing the question to the proposer rather than the answer
alone is what fixed it, and ten runs say it stays fixed.

This question was chosen carefully. An earlier candidate asked about a
service charge cap, and the phrase "service charge" is on page 5, so a
plausible-looking quote would have resolved. A negative test only tests
anything if the document really is silent.

The tests verify the mechanism; the eval measures the model. A test
asserting "the model cites correctly" would be asserting a rate from a
sample of one, and would go red on someone else's machine for reasons
that have nothing to do with the code.

The twenty runs behind these numbers are committed as `eval-runs.jsonl`,
one JSON object per run. Every figure above can be recounted from it
rather than taken on trust, which is the whole point of writing them down.

## What the measurement itself is worth

Counting distinct citation sets by eye is fine for spotting that
something moves. It is not enough to say how much, so I put the collected
runs through AgentVerity, an open-source library I wrote for deciding
whether repeated agent decisions are stable enough to trust. It is a
dev-only dependency here: nothing under `backend/src` imports it, and the
app runs without it installed. I used its `assess` command specifically,
which makes no model calls of its own and only reads runs collected
elsewhere, because I did not want the measuring tool driving the thing
being measured.

Two layers, two different answers.

At the **verdict** layer, supported versus not-supported, nothing
flipped: zero disagreements across ten pairs. But the interval on that is
[0.0%, 27.8%] against a 5% precision target, so the tool declines to
certify it and reports undecided in as many words. It is right to.
Quoting "no verdict flips" off twenty runs would be exactly the
over-claim the library exists to catch, and I am not publishing a number
my own tool refused to stand behind. Settling a 5% flip rate needs far
more runs than this exercise justifies.

At the **citation** layer it does settle, and the answer is that the
feature is stochastic: 2 of 10 pairs disagreed, interval [5.7%, 51.0%],
whose lower bound clears the target. Both disagreements were on the
answerable question. The unanswerable one returned an identical empty
citation list all ten times. Read that result as the interval rather than
as "20%" — the point estimate moves with how runs happen to be paired,
and the interval is the part that is actually established.

So the chip the user sees is measurably unstable, while the supported
flag above it is not measurably unstable and also not certified stable.
Those are different claims with different consequences, and I could not
have separated them by reading the eval output. That is the entire reason
for running an instrument over it instead of eyeballing it, and it is the
sequencing mistake I made once already: build the thing that decides, then
discover afterwards that nobody had established whether its inputs were
stable enough for the decision to mean anything.

Two pieces of off-label use worth declaring. The layer that accepts a
list is meant for tool-call trajectories and compares them in order,
which is correct for a trajectory and wrong for a citation set, where
response order is noise. So citation labels are sorted before comparison,
and that derivation happens in a temporary file rather than in
`eval-runs.jsonl`. Separately, the tool will not accept a bare boolean as
a decision, so the JSONL carries a derived `verdict` string alongside
`answer_supported`, which keeps meaning exactly what the API returns.

## Verification failure degrades to unverified, not to trusted

If the citation call fails or exceeds thirty seconds, `answer_supported`
is set to `false` and the UI says the document does not confirm the
answer. The alternative — leaving it unset, which renders identically to
an ordinary checked answer — means an infrastructure failure silently
produces an answer that looks verified. The answer itself is persisted
before verification starts, so a hung check can't lose text the user has
already read.

## Two findings from the repo, not from my feature

`just check` was red on a clean clone: pyright couldn't run at all,
missing `libatomic1`. And it only ever covered `backend/src`, so
`backend/tests` was outside the gate that was supposed to prove the code
was typed. Both fixed in their own commits before the feature work
started. There was also no `just test` recipe and no test mount, so
pytest couldn't collect. A quality gate that doesn't cover the tests
isn't measuring what its name claims.

## Reviewed by a second model, deliberately

Two instances of the same model fail in correlated ways, so I had Codex
review the diff cold, with no knowledge of my reasoning. Five findings. I
took two: citation quote text wasn't visible to the user, which broke a
promise in SPEC.md, and an unsupported answer's own text didn't
necessarily say it was unsupported. I declined three as out of scope for
this pass: claim-level attribution (above), reworking the streaming
lifecycle, and the partial-resolve change — that last one being the
finding the agent then implemented twice more after I'd rejected it,
which is its own lesson about where the decision has to sit.

## Not built, on purpose

Span-level highlighting inside the PDF, multi-document review, and any
vector store. The first is polish on top of a mechanism that isn't yet
trustworthy at the claim level. The second is the largest real gap in the
product, and half-built it would be worse than not attempted. The third
solves a retrieval problem this app doesn't have at nine pages.

I also considered a spec-driven scaffold for this work and didn't use
one. At this size it would have produced ceremony rather than control —
`SPEC.md` plus `AGENTS.md` plus a failing test per slice gave me the same
guardrails at a fraction of the overhead.

I looked at running this through an established eval framework rather
than a shell script, and didn't. Those frameworks grade answer quality —
faithfulness, relevancy, hallucination — and they do it by asking a
second model to judge. Neither half fits here. Whether a quote is really
in the document is already settled by exact string match, so there is no
judgement to delegate; adding a probabilistic judge on top of a
deterministic check buys nothing and can only introduce disagreement.
What I actually needed to know was whether repeated identical runs agree
with each other, which is a variance question, and none of them treat
that as a first-class measurement. A graded framework becomes the right
tool once support is tracked per claim rather than per answer, because
then there is a real per-claim judgement worth scoring.
