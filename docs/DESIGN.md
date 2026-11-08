# Design notes

## Goals, in priority order

1. A document that states a number, skill or phrase the facts do not support must not pass.
2. Every decision must be explainable to the person reviewing the draft: a line, a column, a
   reason, and for every accepted number the fact it came from.
3. Same input, same output: no model, no network, no randomness, so the checker can gate CI and
   an agent loop.
4. Writing a facts file should take minutes: plain sentences with their sources.

## Decisions

**Facts are sentences, not tables.** A fact is the sentence a person would write ("Led a team
of 12 engineers at ... from 2019 to 2023") plus its source. Numbers are extracted from the
sentence with the same parser that reads documents, so the two sides cannot disagree about
what "€1.2m" means. `numbers:` exists only for figures the sentence does not spell out.

**A number needs a value match and a context match.** Value-only checking was rejected: the
typical error in an edited draft is a true number attached to the wrong claim ("12 engineers"
becoming "12 years"). The context rule is deliberately simple so a reviewer can predict it:
content words within N words of the number, inside its sentence, must overlap the fact's
words. The sentence boundary matters more than the window: without it, a neighbouring sentence
supplies the shared word.

**Default overlap is one word.** Measured on the eval corpus (both hard out-of-context cases,
10 clean documents): with 1 or 2 shared words both hard cases pass and 1 clean document fails;
with 3, one hard case is caught but 5 of 10 clean documents fail. The hard cases share two or
three topic words with the right fact while changing what the number means; a word-overlap
threshold cannot separate them without failing true paraphrases. One word is the default; `min_context_overlap` is exposed so a stricter
team can trade false alarms for misses, and the eval reports the default's misses.

**What "content word" means.** Stopwords, units ("years", "months", "percent"), numbers, words
under three letters and the subject's name are removed, then a small stemmer folds plurals and
a few verb endings. Units are removed on purpose: "12 years" and "12 months" must share a topic
word, not just a unit. The subject's name is removed because it appears in every fact and would
make every number "in context".

**Kinds and currencies.** A percentage matches only a percentage, money only money in the same
currency. A plain number may match money: dropping the currency is not a false claim. Ranges
carry the unit and scale written once ("€2–3m" is two money amounts in millions).

**Skip lists are explicit and documented.** Code, URLs, list markers, versions, times, slashed
numbers and word-number names are not read. Each skip is a place where a false figure passes,
so each is in the README's rules and covered by a test.

**Skills: allow-list, not deny-list.** Any recognised term must be allowed by the facts file.
Terms named in fact sentences are allowed too, because those sentences are true by definition.
Ambiguous short words are case-sensitive; the cost (lower-case "react" is missed) is shown in
the eval.

**Tone is a warning.** Phrase lists for "machine tone" are taste, not truth; failing a document
on taste would teach people to ignore the gate. `--strict` exists for teams that want it.

**MCP tools take text, not paths.** The facts file is fixed at server start. A tool that takes a
path would let any connected client read files the server can read.

**Fail closed on input.** Invalid YAML, unknown keys, duplicate ids and missing sources are
errors with exit code 2. A typo in a key name must not silently disable a check.

## Eval design

The corpus is built by a script from hand-written sentences, so it is reproducible and a test
checks the committed file is current. Each error document contains exactly one injected error,
and a catch only counts when the failing finding is of the injected kind. `hard` cases document
known weaknesses and are expected to fail; they stay in the scores rather than being removed.
Floors in `evals/gate.json` were written after the cases were designed and before the first
run; the first run became `evals/baseline.json`. Because the checker is deterministic, any
change against the baseline is a real behaviour change and fails the gate until the baseline is
re-recorded (`make eval-baseline`) in a reviewed diff.

## Not done (v0.1)

- No LLM-generated eval documents: the corpus measures regressions, not real-world accuracy.
- No dates as a first-class kind (ISO dates are three numbers).
- No per-fact allowed contexts or synonyms beyond what the fact sentence says.
- English only.
