# Most significant technical achievement

## The problem and its context

At Zilch I lead the company's AI engineering. By early 2026 we had agents that
could do real work on our own codebase: read a defect, find the cause, propose
a fix. The hard part was never getting them to produce a change. It was
deciding which changes were allowed to reach a pull request without a human
reading them first.

Both obvious answers fail. Route everything through human review and the agents
save nobody any time, because the reviewing is the expensive part. Let the
agents open pull requests freely and you have put an unreviewed,
non-deterministic author into a regulated payments codebase. We needed a third
thing: a rule that decides, per change, whether this one is safe to ship
unattended.

## Complexity and constraints

Four things made it harder than it sounds.

The output is non-deterministic. The same defect, the same prompt, and the
agent proposes something different. Conventional regression testing assumes a
fixed mapping from input to output, and that assumption is simply not
available.

There is no ground truth at decision time. Whether a fix is correct is only
fully known once it is in production, which is exactly when you no longer want
to find out.

Blast radius varies enormously. A null check in a logging helper and a change
to a settlement calculation are the same size in a diff and nothing alike in
consequence.

And we are a regulated business. Every automated decision has to be
explainable afterwards, to an auditor who was not in the room. That constraint
removed most of the interesting options.

## My approach

I built a release gate: a deterministic rubric that scores every proposed
change and decides whether it opens a pull request or returns to a human.

The rubric is YAML-configured and scores five things: the agent's own reported
confidence, the complexity of the change, its blast radius, the token budget
consumed reaching it, and the outcome of executing it in a sandbox. The
configuration is version-controlled and reviewable, so the policy is a thing
the team argues about in a pull request rather than something buried in a
prompt.

**The alternative I rejected was using a second model as the judge.** It was
the more fashionable option and it would have been faster to build. I rejected
it for one reason: it answers an unexplainable decision with another
unexplainable decision. When an auditor asks why a change shipped, "a language
model thought it was fine" is not an answer. A deterministic rubric can be
read, argued with, and replayed against a past decision to show it would still
hold. That mattered more than any accuracy the model judge might have added.

The trade-off is real and I would name it in any review. A rubric is cruder
than a good judge model. It will refuse changes a human would have waved
through, and that costs throughput. I took that cost deliberately, because in
this domain a false refusal is cheap and a false approval is not.

Around the gate I built the operational layer that makes it inspectable: every
stage of every run correlated in one OpenTelemetry trace, and every gate
decision written to an immutable audit store with the inputs that produced it.

## Impact

The gate is in production and a four-agent triage-and-fix pipeline runs on top
of it, handling at least half of our low-priority defects end to end. Those are
defects no engineer now opens.

The wider result mattered more. The platform became the standard foundation
other teams build agents on rather than staying my one-off, which is the
difference between a demo and infrastructure.

For users the effect is indirect but real. Low-priority defects are the ones
that historically sat in a backlog for months. They now get fixed.

## Reflection

I would build the evidence layer before the gate, not after.

The gate answers "should this change ship". It quietly assumes something nobody
had established: that the agent's behaviour is stable enough for a score to
mean anything. If the same input produces a materially different proposal each
time, a confidence number is describing one sample, not the system.

I only understood this properly afterwards, while measuring how repeatable our
agents' decisions actually were. The finding that stayed with me was that
stability and correctness are not the same axis, and can run in opposite
directions. In one evaluation the most stable model was the least correct. It
was reliably wrong, and any gate keyed on consistency would have trusted it
most.

That became AgentVerity, an open-source library that decides whether repeated
agent decisions are stable and covered enough to be frozen as a regression
baseline. If I started the gate again today, that measurement would come first
and the scoring rubric would consume it, rather than the two being built a year
apart in the wrong order.
