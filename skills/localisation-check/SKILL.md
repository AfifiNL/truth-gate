---
name: localisation-check
description: Use when you translate or localise a document into Dutch or Arabic for a brand that has a truth-gate brand file. Checks your draft against its English source and the market's rules before a person reviews it.
---

# Localisation check

You are localising an English document for one market. A brand file holds that market's rules,
and `truth-gate check-pair` checks your draft against the source and those rules. A person
approves the result; your job is to hand them a draft that already passes.

The same steps apply when you repair a draft someone else wrote: read the rules, run the check
on their draft, then fix what it reports.

## Before you write

1. Find the brand file (usually `brand.yaml`) and the market you are writing for (`nl-NL`, `ar`).
   If either is missing or unclear, ask. Do not guess a market.
2. Run `truth-gate brand <brand file>` to confirm the file is valid and the market is in it.
3. Read that market's section: the terms you must use, the phrases you must not use, the lines
   that must appear, the form of address, and the names in `do_not_translate`.

## Write the draft

- Keep every number from the source, with its meaning. A number written as a word ("twelve")
  counts as a number. Write numbers the way the target language does: Dutch uses a decimal
  comma and a dot for thousands (`1.200,5`).
- Leave every `do_not_translate` name exactly as written, each time it appears.
- Use the market's term every time the source uses the source term. The check only confirms
  that the term appears at least once, so the rest is on you.
- Use no forbidden phrase, in any form. The check finds the listed phrase only, not an
  inflected form of it.
- Include every required line, word for word.

## Check, fix, check again

```bash
truth-gate check-pair <target file> --source <source file> --brand <brand file> --market <market>
```

If `truth-gate` is not on the path, run it from its repository with `uv run truth-gate ...`.

Read every finding. Each one names a side (`source` or `target`), a rule and a reason, and a
line and column when there is one place to point at. A finding on the `source` side means
something in the source is missing from your draft. A finding with no line (a missing required
line) is about the whole text. Fix the draft and run the command again. Repeat until it prints
`PASS`.

A warning does not fail the check. Fix a `format` warning anyway: it means a number is written
the English way.

## What you must not do

- Do not edit the brand file to make a finding go away.
- Do not edit the source to make a finding go away.
- Do not delete a sentence from your draft to make a finding go away. If the sentence is in the
  source, it belongs in the target.

Text that is in the draft but not in the source is different: it should not be there. Remove
it, whether or not the check reported it.

If a rule looks wrong for this text (a required term reads badly here, or the check reports a
number you are sure is right), keep the draft as you believe it should be, leave the finding in
place, and tell the reviewer what the check said and why you disagree. That decision is theirs.

## Hand over

Give the reviewer the draft, the final output of the check, and one line on anything you were
unsure about. The check covers numbers, names, terms, forbidden phrases, required lines and the
Dutch form of address. It does not judge whether the translation reads well or means the same
as the source. Say so if the reviewer asks what "PASS" covers.
