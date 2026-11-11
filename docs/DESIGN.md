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

**Moved numbers are judged per clause.** The overlap rule alone passes a true number attached
to another claim when the two claims share a topic word ("26 hours to 9 hours" shares "support"
with a fact about a team of 9). The added rule compares facts: if a fact that does *not*
contain the number matches the number's clause by `misplaced_margin` (2) or more words than the
best fact that does, the number is flagged as moved. It uses the clause, not the sentence,
because one sentence often joins two facts ("Holding a BA ... in 2014, Jordan wrote 60
articles ..."): measured on the dev half of the model-written set, the sentence-level version
caught the moved number but also failed that true sentence (a test keeps that comparison). A
review then found that comma-bounded clauses were not enough: "Automated 35% of routing and
wrote 60 help-centre articles ..." flagged 35%, and the mirror sentence flagged 60. Clauses
therefore also end at "and", "but", "while" and "whereas"; both sentences are tests. This rule
came from looking at dev documents. On held-out it changed nothing (the overlap rule already
caught both moved numbers there), and it changed nothing on the hand-built set; the two
hand-built hard cases still pass because no other fact matches them better. "No false alarm"
only holds for documents close to the facts' wording, which is what the model wrote.

The comparison runs on indexes built once per facts file (value to facts, word to facts) and is
cached per document by the fact-words around each number, so its cost does not grow with every
fact: a 200,000-character document against 300 facts takes about 1.2 s in the tests (it was
over three minutes before the indexes).

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

## The model-written set (evals/llm)

Protocol, in order: (1) the request list, its dev/held-out split and the prompt were written
and fixed; (2) 48 documents were generated with one model call each (plus one retry after a
rate limit: 49 calls); (3) every document, held-out included, was read and labelled, with a
reason, before the checker was run on any of them; documents that did not follow their
instruction were labelled `dropped`, never edited; (4) the checker was run on dev, one rule was
added (above), and the checker was frozen; (5) held-out was run once. Labels are limited to what
truth-gate checks (numbers, skills, blocked phrases); relations the model added are recorded as
a finding, not as errors, because the checker does not claim to check them.

What this protocol does not give: a blind held-out half. Labelling read the held-out documents,
and the decision not to add "Excel" to the vocabulary was made knowing the held-out half uses
it. The held-out number is a first run after freezing, not a blind estimate, and from then on
held-out is a regression set (every `make check` scores it).

Review round 2 applied the drop rule evenly: a "moved" number must keep its value and its unit,
so L12 ("22%" became "22 months") is dropped like L20 ("4 hours" became "4 million"), and the
label test compares value and unit instead of digit strings. The scores were re-recorded after
that change and after the clause fix; both are in the history.

History: the generated documents, the labels, the rule and the first baselines landed in one
commit, because the rules the build ran under forbid rewriting history, unpushed history
included (no reset). The order of events above is the record; the review-round-2 changes are separate
commits.

The gate for this set is regression-only (`evals/llm/gate.json` has no floors) because any
floor would have been chosen after seeing the numbers. It fails when a metric gets worse, when
the number of scored documents changes, or when a document that was handled correctly no
longer is. Hashes in the labels prove the documents were not edited after labelling; the raw
API responses of this run were not kept.

## Not done

- The model-written set is one model, one prompt, one run, and errors the model was asked to
  make; it does not measure how often a model errs unprompted.
- No dates as a first-class kind (ISO dates are three numbers).
- No per-fact allowed contexts or synonyms beyond what the fact sentence says.
- English only.

# v0.2: the pair check

The spec is [SPEC-v0.2.md](SPEC-v0.2.md), written before the code. This part records the
decisions and where the build differs from it.

## Decisions

**Truth flows one way.** Facts, then the English source, then the localised target. The target
is compared with the source, never with the facts: a fact is an English sentence, and the
context rule compares English words. A Dutch sentence shares none of them.

**English reading is untouched.** `numbers.scan` takes a `locale`, and anything but `en` goes to
`locales.scan_target`. The English path is the v0.1 code, and both v0.1 baselines are unchanged.

**One token, two readings.** `1,200` is 1200 in English and 1.2 in Dutch. The Dutch reader
follows Dutch rules without guessing what the writer meant, because the common error is a number
copied from the source as it stands. The pair check then reports 1.2 against a source of 1200
and says why. A dot that cannot be a thousands mark (`1.5`) is read as a decimal and reported as
a warning: the value is right and the format is English.

**Arabic is folded before anything is matched.** Direction marks, diacritics and the elongation
character are removed, the alef forms become one, and Arabic-Indic and Persian digits and signs
become ASCII. An index maps every folded character to its place in the original, so findings
point at the text the writer sees. After folding, digits are read by the English rules.

**A percentage must stay a percentage; a currency or a unit may become a plain number.** The
scanner knows few currency words in Dutch and Arabic and no spaced units ("40 GB"). Demanding
the same kind on both sides would fail true translations, so money or a unit on one side may be
a plain number on the other. Two different currencies, or two different units, do not match.

**A missing thing points at the source.** A number, name or term that is absent from the target
has no place in the target, so the finding gives the line in the source (`side: source`).

**Word lists are data.** Number words, scale words, percent words, currency words, particles and
suffixes are in `data/nl.txt` and `data/ar.txt` with a comment per group, so a speaker of the
language can review them without reading Python.

## Where the build differs from the spec

- **Source texts for the experiment were written by hand**, not generated. That spent no calls
  and kept every number format and term under control.
- **Dutch thousands by a space**: only a no-break or thin space groups digits. A plain space
  would join "in 2019 300 mensen" into one number.
- **Arabic number words go further than one to ten.** The first run on the dev half reported
  "اثني عشر" (twelve) and "ساعتين" (two hours, a dual noun) as missing numbers. Added: eleven
  to nineteen, the tens, a unit joined to a ten ("خمسة وعشرين"), and a short list of dual
  nouns for time ("ساعتين", "شهرين"). A dual noun outside that list is still not read.
- **Arabic terms match more than one stripped particle.** The dev half had "شركة نقل" for the
  listed "شركة النقل" and "شحنتك" for "شحنة". For terms the definite article is now ignored on
  every word, and the last word may carry a pronoun suffix (a final ة opens to ت). Forbidden
  phrases keep the article: "الأرخص" (the cheapest) is not "أرخص" (cheaper).
- **`truth-gate brand FILE`** validates a brand file. The skill needs it; the spec did not
  list it.
- **`list_facts` returns the whole brand file**, not one market's rules, because the tool has no
  market argument.
- **The skill walk-through** was recorded from an agent that was pointed at the skill file and
  given a failing draft, not from a session where the skill loaded by itself.

## What the dev half showed and what was left alone

The checker first ran on the 80 dev documents after their labels were committed. It disagreed
with 13 labels: 11 false alarms and 2 misses. Every one had been predicted in the label notes
while reading. After the two changes above, 3 differ:

- "between 8 and 12 in the morning" became "tussen 08:00 en 12:00 uur". Clock times are
  skipped, so 8 and 12 are reported as missing. Matching a bare number to a clock time would let
  a wrong time pass, so this stays a false alarm.
- Twice the model wrote a transliteration and kept the name in brackets:
  "إكزامبل فريت (ExampleFreight)". The name is there as often as in the source, so the count
  rule passes. The checker cannot know what a transliteration of a name looks like. A brand that
  sees this can add the transliteration to `forbidden`.

The pair corpus has nine hard cases that pin these and the other known limits: a reversed
meaning, two numbers swapped between nouns, an inflected forbidden phrase, a clock time, a long
Dutch compound number, a name replaced by a pronoun, an unlisted Arabic dual, a suffix on a
broken plural, and Arabic hundreds.

