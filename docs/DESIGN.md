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
supplies the shared word. Every line break is a boundary too, so a list item can never borrow
context from the item above it ("1. Hired engineers / 2. Owns 12 cats"). The price is that in
hard-wrapped prose a number near a line end loses the next line's words: a false alarm, which
is the cheaper error.

**Default overlap is one word.** Measured on the eval corpus (both hard out-of-context cases,
11 clean documents): with 1 or 2 shared words both hard cases pass and 1 clean document fails;
with 3, one hard case is caught but 5 of 11 clean documents fail. The hard cases share two or
three topic words with the right fact while changing what the number means; a word-overlap
threshold cannot separate them without failing true paraphrases. One word is the default;
`min_context_overlap` is exposed so a stricter team can trade false alarms for misses, and the
eval reports the default's misses.

**What "content word" means.** Stopwords, units ("years", "months", "percent"), numbers, words
under three letters and the subject's name are removed, then a small stemmer folds plurals and
a few verb endings. Units are removed on purpose: "12 years" and "12 months" must share a topic
word, not just a unit. The subject's name is removed because it appears in every fact and would
make every number "in context".

**Kinds, currencies and units.** A percentage matches only a percentage, money only money in
the same currency, a glued unit ("40GB", "50x") only the same unit. A plain number may match
money or a unit-bearing number: dropping the currency or unit is not a false claim. A currency
marker the scanner reads but cannot name ("5 Martian dollars", "€5 USD") becomes a currency
that matches no fact. Ranges carry the unit and scale written once ("€2–3m" is two amounts in
millions), but only across a dash, only when the scaled range stays ordered ("500–2m" stays
500 and 2 million) and never onto a year ("2019 – 18%").

**The scanner is fail-closed; its skip list is complete.** Every run of digits is a claim unless
one of the rules in `numbers.SKIP_RULES` applies (times, slashed numbers, multi-dot versions,
non-thousands commas, digits glued to a preceding letter, short word-hyphen names), or the
digits sit in masked code, comments, URLs or list markers. An earlier version used one large
regex that silently dropped tokens it could not place ("50x", "$5B", "1990s"); now unknown
glued letters become a unit that a fact must share. Each skip is a place where a false figure
passes, so each is listed in the README, reported by `scan()` and covered by a test.

**Masking is for numbers only.** Code spans and comments are masked so that a port number or a
line count in a code sample is not read as a claim. Skills, blocked phrases and tone are checked
on the original text: "`guaranteed results`" in backticks is still a blocked phrase.

**Linear time and a size cap.** Every pattern is linear: fences are matched line by line (an
unclosed fence stops fence handling, so the rest is checked as prose), HTML comments with
`str.find`, and link targets exclude brackets so they cannot rescan. The context window uses
precomputed word offsets and binary search. Documents above 200,000 characters are rejected
(CLI exit 2, MCP tool error) rather than checked in part; the worst case at the cap (40,000
numbers) takes about 1.5 s on the development machine.

**Skills: allow-list, not deny-list.** Any recognised term must be allowed by the facts file.
Terms named in fact sentences are allowed too, because those sentences are true by definition.
Ambiguous short words are case-sensitive; the cost (lower-case "react" is missed) is shown in
the eval. A capitalised ambiguous word opening a sentence ("Swift responses ...") is a warning
rather than an error, and "Go-to" is never the language: this trades a possible miss at a
sentence start (visible under `--strict`) for not failing ordinary English.

**Tone is a warning.** Phrase lists for "machine tone" are taste, not truth; failing a document
on taste would teach people to ignore the gate. `--strict` exists for teams that want it.

**MCP tools take text, not paths.** The facts file is fixed at server start. A tool that takes a
path would let any connected client read files the server can read.

**Fail closed on input.** Invalid YAML, duplicate YAML keys, unknown keys, duplicate ids,
missing sources, non-integer thresholds (`min_context_overlap: true`) and non-UTF-8 files are
errors with exit code 2. A typo or a repeated key must not silently disable a check.

## Eval design

The corpus is built by a script from hand-written sentences, so it is reproducible and a test
checks the committed file is current. Each error document contains exactly one injected error,
and a catch only counts when the failing finding is of the injected kind. `hard` cases document
known weaknesses and are expected to fail; they stay in the scores rather than being removed.
Floors in `evals/gate.json` were written after the cases were designed and before the first
run; the first run became `evals/baseline.json`. Because the checker is deterministic, every
change in a metric is a real behaviour change. The gate fails when a metric gets worse than the
baseline (or breaks a floor); an improvement passes, and re-recording the baseline
(`make eval-baseline`, a reviewed diff) locks it in.

Review round 1 changed the corpus: the clean-document builder skipped one paraphrase, and
fixing it added an eleventh clean document and shifted the dev/test assignment. The baseline
was re-recorded for that reason. Per-split false-alarm rates move in steps of one document
(dev has 6 clean documents, test 5): the one known false alarm (the CSAT abbreviation) now sits
in dev at 0.167, under the 0.20 ceiling; in the first corpus it sat in test at exactly 0.20.
The ceiling was not changed, and it is coarse: a second false alarm in either split fails the
gate.

## Not done (v0.1)

- No LLM-generated eval documents: the corpus measures regressions, not real-world accuracy.
- No dates as a first-class kind (ISO dates are three numbers).
- No per-fact allowed contexts or synonyms beyond what the fact sentence says.
- English only.
