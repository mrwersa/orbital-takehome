# Cited answers and an honest not-found path

## 1. What this changes

Today, an answer about the uploaded document carries no way to check it against the source, and the "sources cited" count next to it doesn't actually mean anything was verified. Once this is done, a user can ask a question and get back an answer where every claim traces to an exact quote and page number from the document. They can click a citation to jump the viewer straight to that page, and if the document simply doesn't say something, the assistant says so plainly instead of guessing. Every citation shown has already been checked against the actual document text before it is ever displayed.

## 2. In scope

1. An answer that the document supports arrives with one or more citations, each carrying the exact quoted text and the page number it came from.
2. The quoted text of each citation is visible to the user, not just the page number.
3. Clicking a citation moves the document viewer to that citation's page.
4. An answer arriving on its own never moves the document viewer — only a click does.
5. Every citation shown to the user has been checked against the document's stored text and found to match, allowing only for whitespace and line-wrap hyphen differences.
6. A proposed citation that doesn't match the document text is dropped and never shown to the user.
7. An answer can carry more than one citation.
8. When the document doesn't contain the answer, the response says so plainly, visually distinct from a normal answer but not styled as an error or warning.
9. Citations and the not-found state are saved with the message and are still present after a page refresh.
10. This works for any PDF the app can already read — nothing is tailored to the sample lease document's structure or numbering.
11. The "sources cited" count shown to the user reflects only citations that were actually checked and matched, not raw mentions of words like "section" or "page" in the answer text.

## 3. Out of scope for today

- Multiple documents per conversation — today's app is built around one document per conversation.
- Export to a report — separate from answering a question with a citation.
- Checklist-driven review — separate from answering a question with a citation.
- A coverage view of what's been checked across the document — separate from answering a question with a citation.
- Highlighting the citation's exact span inside the rendered document page — the quote and page number identify the citation; pinpointing it visually on the page is a separate problem.

## 4. Deliberately not doing, ever

- Trusting a citation because the model claims it, without checking it against the document text. Verification is the entire point of this feature, not an enhancement to it.
- Reporting any "sources cited" number that isn't backed by that check. A number a user can't trust is worse than no number.
- Moving the document viewer on its own when an answer arrives. It must never be pulled out from under someone who is mid-read — only a deliberate click moves it.
- Presenting "the document doesn't say" as an error or failure state. It's a legitimate, useful answer and should read as calm and plain, not alarming.
- Adding new dependencies to build this. It's built with what's already in the app.
- Special-casing the sample document's structure, clause numbering, or layout. The feature has to hold up generically, for any PDF the app can read.

## 5. How I will know it works

- Ask a question the document answers: the response carries at least one citation, each with a quote and a page number, and the quote is visible.
- Click a citation: the document viewer jumps to that page.
- Ask a follow-up question: the viewer does not move on its own when the new answer arrives.
- Ask a question the document doesn't answer: the response says so plainly, and reads as a normal answer, not an error.
- Refresh the page after an exchange: the citations and any not-found state are still there.
- Ask the identical question ten times: check whether the same citation set comes back each time.

The one number I will report: what fraction of the citations the model proposes actually resolve against the document text.
