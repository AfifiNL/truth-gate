# truth-gate

A deterministic check for AI-written documents (reports, product pages, proposals, press
releases, speaker bios) against a **facts file** you control:

- every **number** in the document must equal a number in a fact **and** be used in that fact's
  context (a true "12" from "a team of 12 engineers" does not license "12 years of experience");
- every **skill or tool** the document names must be listed in the facts file (useful wherever a
  draft describes what a person or team can do, a CV included);
- **blocked phrases** fail the document;
- a **tone lint** warns about machine-sounding phrases (never fails).

It ships as a **CLI** (exit code 0/1, text or JSON report) and an **MCP server**, so an agent can
check its own draft before a person reads it. No model is involved in checking: the same
document and facts always give the same result.

Since v0.2 it also checks a **localised draft** (Dutch or Arabic) against its English source and
a **brand file** with the rules for one market: numbers must survive the translation, names
that must not be translated must stay as written, the market's terms must be used, forbidden
phrases fail, required lines must be there. See [Localised drafts](#localised-drafts-the-pair-check).

## What it does

```text
$ truth-gate check examples/fail.md --facts examples/facts.yaml
FAIL: 4 error(s), 2 warning(s); 7 number(s) and 3 skill mention(s) checked
  ERROR   3:21 number: 15 does not appear in any fact
  ERROR   4:1 blocked: blocked phrase 'guaranteed results'
  ERROR   4:51 skill: 'Kafka' is not a skill in the facts file
  ERROR   7:10 number: 12 appears in a fact, but the words around it share no topic with that fact (number used out of context) [facts: team-lead]
  WARNING 7:36 tone: machine-tone phrase 'seamless'
  WARNING 7:46 tone: machine-tone phrase 'cutting-edge'
  traced numbers:
    3: 2019 <- team-lead (engineer, examplefreight, ltd, team)
    3: 2023 <- team-lead (engineer, examplefreight, ltd, team)
    6: 18% <- cloud-costs (cloud, cost, cut, monthly)
    6: 2022 <- cloud-costs (cloud, cost, cut, monthly)
    8: €1.2m <- budget (budget, platform)
```

Every accepted number is **traced** to the fact that supports it, with the words they share, so
a reviewer can check the evidence instead of re-reading the whole document. `--json` prints the
same report as JSON.

## Quick start (60 seconds)

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
make install     # .venv from uv.lock
make demo        # checks examples/pass.md (PASS) and examples/fail.md (FAIL)
make demo-pair   # a Dutch and an Arabic draft against their English source (PASS, PASS, FAIL)
make check       # lint, strict mypy, tests, eval gate: exactly what CI runs
```

Your own document:

```bash
uv run truth-gate facts my-facts.yaml                      # validate; lists the numbers it found
uv run truth-gate check draft.md --facts my-facts.yaml     # exit 0 = pass, 1 = fail, 2 = bad input
uv run truth-gate check draft.md --facts my-facts.yaml --strict --json   # warnings fail too
```

## The facts file

```yaml
subject: Robin Example          # the subject's own name is never counted as shared context
facts:
  - id: team-lead
    text: Led a team of 12 engineers at ExampleFreight Ltd from 2019 to 2023.
    source: employment reference letter, ExampleFreight Ltd, 2023   # where a reviewer checks it
  - id: budget
    text: Managed a platform budget of €1.2 million per year.
    source: budget approval e-mail, 2022
    numbers: []                 # optional: numbers the text does not spell out
                                # ({value, unit: plain | percent | ISO currency code})
skills:
  - Python
  - name: PostgreSQL
    aliases: [Postgres]
blocked_phrases: [guaranteed results, world-class]
# optional: vocabulary (extra terms to recognise), tone_phrases (replaces the built-in list),
# min_context_overlap (default 1), context_window (default 8 words),
# misplaced_margin (default 2; 0 switches the moved-number rule off)
```

Numbers are read from each fact's text, so a fact is written once, in plain words. Unknown keys
and duplicate keys are rejected, so a typo or a second `blocked_phrases:` line cannot silently
switch a check off.

## The rules, exactly

**Numbers.** Every run of digits is read as a number unless a skip rule below applies, plus
written-out numbers ("twelve", "twenty-five", and "one"/"a" when a scale word follows: "one
million", "a thousand"). Read with each number: percentages (`%`, "percent", "per cent",
"pct"), money (`€ $ £ ¥ ₹`, `US$ C$ A$ NZ$ HK$ S$`, ISO codes such as `EUR USD GBP CHF CAD`
before or after the number, "euros", "dollars", "francs", "pesos" ..., with a country
adjective where given: "Canadian dollars" is CAD, an unknown adjective matches nothing), scales (`k`, `m`, `B`, `bn`,
"hundred", "thousand", "million", "billion"), and units glued to the number (`50x`, `100ms`,
`40GB`, `1990s`). Ranges written with a dash (`10–15%`, `€2–3m`) give both ends the unit; a
scale is carried over only if the range stays ordered, and a year never takes a unit ("from 500
to 2m" is two separate numbers). A document number passes when:

1. some fact contains an equal quantity: same value; a percentage only matches a percentage;
   money only matches money in the same currency (contradictory markers such as `€5 USD` match
   nothing); a number with a glued unit only matches the same unit; a plain number may match
   money or a unit-bearing number (leaving out the currency or unit is not a false claim); and
2. at least `min_context_overlap` content words within `context_window` words either side of the
   number, **in the same sentence and on the same line**, also appear in that fact's text.
   Every line break ends a sentence, so list items and wrapped lines never lend each other
   context. Content words are stemmed lightly ("conferences" = "conference"), and stopwords,
   units ("years", "months"), numbers and the subject's name are ignored; and
3. the number's own **clause** (bounded by `, ; :`, brackets, a spaced dash, or the words
   "and", "but", "while", "whereas") does not match a fact *without* this number by
   `misplaced_margin` (2) or more words than it matches the best fact *with* it. This catches a
   true number moved to another claim when the two claims share a topic word: "reduced
   first-response time for support tickets from 26 hours to 9 hours" shares "support" with the
   fact about a team of 9, but four words (first-response, hour, support, ticket; "time" is a
   unit word) with the response-time fact.

**Not checked** (each is a place where a false figure passes, so the list is complete):

- numbers inside fenced code (``` and ~~~), inline code, HTML comments, URLs and link targets;
  an unclosed fence or comment is not treated as code, so its numbers are checked;
- ordered-list markers where a Markdown list can start (after a blank line, inside a list, or a
  list starting at 1); a wrapped line that merely starts with "40. " is checked;
- times (`10:30`); numbers joined by a slash (`24/7`, `03/2021`); version strings with two or
  more dots (`3.12.1`); comma-separated digits that are not thousands groups (`1,5`, `1,2,3`);
  digits glued to a preceding letter (`v2`, `Q3`, `H2O`, `B2B`); word-hyphen-number names below
  four digits (`COVID-19`; a four-digit year after a hyphen, `mid-2019`, is checked);
- the words "one" and "a" without a scale word ("one of the reasons", "a team").

**Skills.** 110 built-in tool and skill entries with aliases (`src/truth_gate/data/skills.txt`),
plus the facts file's skills and `vocabulary`, matched as whole terms, longest first, with
aliases mapped to one name (`K8s` → Kubernetes). Short or ambiguous terms are case-sensitive
(`Go`, `R`, `React`, `Spark`, `Helm`), so "teams react quickly" is not a claim about a library.
A capitalised ambiguous word that opens a sentence ("Swift responses matter", "Spark joy") is a
warning, not an error, and "Go-to-market" is never the language. A term passes if it is a
listed skill or appears in a fact's text (a fact that says "from MySQL to PostgreSQL" makes
mentioning MySQL true).

**Blocked phrases** match case-insensitively as whole phrases, across line breaks. **Tone**
phrases (`src/truth_gate/data/tone.txt`) are warnings only; `--strict` makes them fail. Skills,
blocked phrases and tone are checked on the whole text, inside code spans too: masking applies
to numbers only.

**Input limits.** Documents are capped at 200,000 characters (CLI and MCP); a longer document
is rejected with exit code 2 (or an MCP tool error), never checked in part. Non-UTF-8 input
exits 2. Every pattern runs in linear time.

## MCP server

```bash
uv run truth-gate serve --facts examples/facts.yaml     # stdio
```

Tools: `check_document(text)` returns the report above as structured content; `list_facts()`
returns the facts, the allowed skills and the blocked phrases. The facts file is fixed when the
server starts, and tools accept document text only, never a path, so a client cannot make the
server read other files. Example client entry:

```json
{"mcpServers": {"truth-gate": {"command": "uv",
  "args": ["run", "--directory", "/path/to/truth-gate", "truth-gate", "serve",
           "--facts", "/path/to/facts.yaml"]}}}
```

The tests drive the server through the SDK's in-process client (with and without the full
protocol handshake) and once through a real `truth-gate serve` subprocess over stdio.

## Localised drafts: the pair check

```text
$ truth-gate check-pair examples/pair/fail.nl.md --source examples/pair/source.en.md \
      --brand examples/pair/brand.yaml --market nl-NL
FAIL (nl-NL): 7 error(s), 1 warning(s); 5 number(s) in the source, 5 in the target
  ERROR   source 1:3 name: 'TrackBoard' must stay as written: 2 time(s) in the source, 1 in the target
  ERROR   source 3:28 term: the source says 'shipment'; the target has none of: zending, zendingen
  ERROR   target 3:34 number: 1.2 is not in the source; the source has 1200 (line 3): in Dutch '1,200' has a decimal comma
  WARNING target 3:61 format: '98.5%' is English number format; Dutch writes a decimal comma
  ERROR   target 5:26 address: 'uw' is formal; this market is addressed informally
  ERROR   target 5:54 forbidden: forbidden phrase 'gratis verzending'
  ERROR   target 6:27 number: 20 is not in the source; the source has 12 (line 6)
  ERROR   target required-line: required line is missing: 'Prijzen zijn exclusief btw.'
```

Truth flows one way: facts → English source → localised target. The source is checked against
the facts with the rules above (pass `--facts`), and the target is checked against the source
and the market's rules. The target is never checked against the facts directly: the facts are
English sentences, and the context rule compares English words.

A finding about something missing from the target points at the place in the source
(`source 3:28`), because there is no place in the target to point at.

### The brand file

```yaml
brand: ExampleFreight
source_locale: en
do_not_translate: [ExampleFreight, TrackBoard]   # must appear unchanged in every target
markets:
  nl-NL:
    address: informal            # "je"; "u" and "uw" fail. formal: "je", "jij", "jouw" fail
    terms:
      - source: shipment         # when the source says this ...
        target: [zending, zendingen]   # ... the target must use one of these
    forbidden: [gratis verzending, vracht]
    required_lines:
      - "Prijzen zijn exclusief btw."
  ar:
    terms:
      - source: shipment
        target: ["شحنة", "شحنات"]
```

Unknown keys and duplicate keys are rejected, as in the facts file. `truth-gate brand FILE`
validates a brand file and lists its markets. All example content is fictional.

### The pair rules, exactly

1. **number.** Every quantity in the source must appear in the target with the same value, and
   the target must not contain a quantity the source lacks. Quantities are compared over the
   whole document. A percentage must stay a percentage. Money must keep its currency, but money
   or a glued unit on one side may be a plain number on the other, because the target may write
   the currency or unit in words the scanner does not know. When one number replaced another,
   the finding names both.
2. **name.** Each `do_not_translate` name must occur in the target as written, at least as
   often as in the source. A Dutch genitive (`ExampleFreights`) and an Arabic particle written
   against the name count as the name.
3. **term.** When the source contains a `source` term (singular or plural), the target must
   contain one of its `target` forms at least once. It is not counted per occurrence. Dutch: the listed forms, as whole words. Arabic: see
   below.
4. **forbidden.** A `forbidden` phrase anywhere in the target fails, as a whole phrase.
5. **required-line.** Every `required_lines` entry must be in the target, compared after
   collapsing whitespace and ignoring case.
6. **address** (Dutch, when `address` is set). `informal` fails on `u`, `uw`, `uzelf`; `formal`
   fails on `je`, `jij`, `jou`, `jouw`, `jullie`. An abbreviation such as `a.u.b.` is not a
   pronoun.

A **format** warning (Dutch) marks a number written the English way (`1.5`). Warnings never
fail; `--strict` makes them fail. Numbers in code, comments, URLs and link targets are not
compared, as in the single-document check.

### How numbers are read per language

| | English | Dutch | Arabic |
|---|---|---|---|
| Decimal mark | `.` | `,` | `.` or `٫` |
| Thousands mark | `,` | `.`, or a no-break or thin space | `,` or `٬` |
| Digits | `0-9` | `0-9` | `0-9`, `٠-٩`, `۰-۹` |
| Percent | `%`, percent | `%`, procent, pct | `%`, `٪` (before or after the number), بالمئة, في المئة |
| Scale words | thousand, million | duizend, miljoen, miljard, mln, mld | ألف, آلاف, مليون, ملايين, مليار |
| Number words | one to ninety-nine | twee to negentig, `vijfentwintig`, `tweeduizend` | two to ninety-nine, and the dual nouns listed in the data file |

So `1,200` is one thousand two hundred in an English source and one point two in a Dutch
target. A Dutch draft that copies `1,200` from the source fails, which is the mistake this rule
exists for.

The word lists are data files a speaker of the language can read and correct:
[`data/nl.txt`](src/truth_gate/data/nl.txt) and [`data/ar.txt`](src/truth_gate/data/ar.txt).

### How Arabic text is matched

Before anything is matched, Arabic text is folded: Unicode direction marks and isolates are
removed (so a Latin name wrapped in them still matches), diacritics and the elongation character
are removed, and the alef forms become one. Findings still point at the original text.

- A number word, a term or a forbidden phrase may carry one attached particle from a fixed
  list: the conjunctions, the attached prepositions and the definite article
  (`وبالشحنة` contains the term `شحنة`).
- For **terms** the definite article is ignored on every word (`شركة نقل` is the term
  `شركة النقل`), and the last word may carry a pronoun suffix (`شحنتك`, "your shipment", uses
  the term `شحنة`).
- A few short number words take no particle except the conjunction: `ست` is six, and `لست`
  ("I am not") must not be read as "for six".

### For agents

`truth-gate serve --facts FILE --brand FILE` adds a tool, `check_localised(source_text,
target_text, market)`, which returns the pair report as structured content. Like
`check_document` it takes text only, never a path.

[`skills/localisation-check/SKILL.md`](skills/localisation-check/SKILL.md) is an agent skill.
It tells an agent that localises a document to read the market's rules first, write the draft,
run the check, fix every finding and hand over the draft with the passing report. It forbids
three things: editing the brand file, editing the source, and deleting a sentence to make a
finding go away. [docs/SKILL_WALKTHROUGH.md](docs/SKILL_WALKTHROUGH.md) records one session.

## Evals

`evals/cases.jsonl` holds 35 synthetic documents about a fictional person (`evals/facts.yaml`,
different from the examples), built deterministically by `evals/build_cases.py` from
hand-written sentences: 11 clean documents and 24 with exactly one injected error (wrong number,
number out of context, invented skill, blocked phrase). Five cases are marked `hard`: they were
written to show known weaknesses and are expected to be missed. Split: alternate cases go to
`dev` and `test`.

- **catch rate**: share of error documents that fail **for the injected reason** (a wrong
  number must fail on a number finding, not on a stray tone hit);
- **false-alarm rate**: share of clean documents that fail.

Results of `make eval` (deterministic, so these are exact):

| scope | cases | catch rate | false-alarm rate | wrong number | out of context | invented skill | blocked phrase |
|---|---|---|---|---|---|---|---|
| all | 35 | 0.833 | 0.091 | 1.000 | 0.714 | 0.833 | 0.800 |
| dev | 18 | 0.833 | 0.167 | 1.000 | 0.667 | 1.000 | 0.667 |
| test | 17 | 0.833 | 0.000 | 1.000 | 0.750 | 0.667 | 1.000 |

Every miss is one of the five `hard` cases:

- *"Answered 26 support tickets per day."* (26 is a response time in hours) and *"Raised customer
  satisfaction across 18 product lines."* (18 is a number of months) pass: they share topic
  words with the right fact but change what the number means. A stricter overlap setting
  catches one of them only by failing half the clean documents (see DESIGN.md).
- *"Lifted CSAT to 92%, up from 81%."* fails although it is true: the fact says "customer
  satisfaction score", and an abbreviation shares no word with it. Writing the abbreviation
  into the fact fixes it.
- *"Built a small react front end"* passes: lower-case "react" is not read as the library.
- *"Response times were guaranteed by contract."* passes the blocked phrase "guarantee":
  blocked phrases are whole phrases, not word stems.

The gate (`evals/gate.json`) fails `make check` when, in any scope, the catch rate drops below
0.75, the false-alarm rate exceeds 0.20, any metric gets worse than in `evals/baseline.json`,
the number of cases changes, or any case that was handled correctly no longer is (an
improvement passes; re-record the baseline to lock it in). Tests prove the gate works: a checker that skips numbers, ignores context
or ignores skills fails it.

**What these numbers are not.** The corpus was written by the same author as the checker, from
the same rules; it is a regression gate and a description of behaviour, not an accuracy
estimate for real AI-written documents. The second set below is closer to that.

### Model-written set

`evals/llm/documents.jsonl` holds 48 short documents written by `gemini-3.6-flash` (Vertex AI,
thinking level low, 2026-11-08) from the same synthetic facts: 16 each of a speaker bio, a
service blurb and an annual-report paragraph. Half were asked to use only the facts; the other
half were asked to introduce exactly one error of a named type (6 each: wrong number, a number
moved to another claim, an invented tool, a blocked phrase) and to say what they changed. The
prompt sets everything in a fictional world; apart from software product names (the skills
list and the tools the model invented) no real people, places or companies appear: a test
checks every capitalised word, sentence openers included, against the fictional facts, the
skills list, a reviewed list of English sentence openers and the one tool named in that
document's label. `evals/llm/generate.py` regenerates the set and costs about 48 model calls; it
refuses to make any call unless `TG_MAX_LIVE_CALLS` is set.

Every document was **labelled by reading it before the checker was run on any of them**
(`evals/llm/labels.jsonl`, one reason per document). The labels record each document's
SHA-256, and `tests/test_llm_eval.py` checks it: that proves the text was not edited after
labelling, not that it is the model's raw output (the raw API responses of this run were not
kept; `generate.py` keeps them from now on). The same test checks, with a small parser of its
own rather than truth-gate's, that each label's evidence holds, comparing value and unit: an
injected quantity is absent from the facts, a moved one keeps the fact's value and unit, the
document's other quantities all come from the facts, an invented tool is absent from the facts
file, and a clean document uses no quantity the facts lack.

What the model did:

- **Injected errors: 21 of 24 followed the instruction.** Wrong number 6/6, invented tool 6/6,
  blocked phrase 6/6, moved number 3/6. Asked to move a number unchanged, the model once wrote
  "4 million" hours (a changed value), once turned "22%" into "22 months" (a changed unit) and
  once swapped two numbers; all three are dropped from the scores, none edited.
  For the blocked phrase it chose "rockstar" all six times; the invented tools were Tableau (2),
  Excel (2), Salesforce and Docker.
- **Clean documents: 24 of 24 used only figures, tools and phrases from the facts.** But all 24
  also linked facts with a relation the facts do not state: a time ("during this period"), a
  cause ("these improvements raised satisfaction") or an employer ("at ExampleParcel Co,
  Jordan raised the score"). truth-gate does not check relations, so these pass.

Scores (45 scored documents; the dev/held-out split was fixed before generation):

| scope | documents | catch rate | false-alarm rate | wrong number | moved number | invented tool | blocked phrase |
|---|---|---|---|---|---|---|---|
| all | 45 | 0.905 (19/21) | 0.000 (0/24) | 1.000 | 1.000 | 0.667 | 1.000 |
| dev | 22 | 0.900 (9/10) | 0.000 (0/12) | 1.000 | 1.000 (1/1) | 0.667 | 1.000 |
| heldout | 23 | 0.909 (10/11) | 0.000 (0/12) | 1.000 | 1.000 (2/2) | 0.667 | 1.000 |

Both misses are "Excel", which is not in the built-in vocabulary ("excel" is also an English
verb). It was not added, partly because the held-out half uses it too: that decision already
used held-out content.

One checker change was made after looking at `dev`: rule 3 above (moved numbers). It catches
the one moved number on dev, which the overlap rule passed. On `heldout` the overlap rule alone
already caught both moved numbers, so the rule changed nothing there (rule off: all 0.857, dev
0.800, held-out 0.909), and it changed nothing on the hand-built set. It raised no false alarm
on these documents, which stay close to the facts' own wording; its first version did raise
false alarms on constructed sentences that join two facts with "and" ("Automated 35% of routing
and wrote 60 help-centre articles ..."), which is why clauses now also end at "and", "but",
"while" and "whereas". Its evidence is one dev document plus "no harm" elsewhere, not a measured
improvement.

**Held-out is a regression set now, not a blind one.** It was run once, after the checker was
frozen, and that first result is the one above; but labelling read every held-out document, the
Excel decision used held-out content, and from now on `make check` scores both halves on every
run and `make eval-baseline` re-records both. `--split dev` scores dev only (and a dev-only
baseline update leaves held-out untouched). The gate for this set is regression-only: the
results were seen after the fact, so no floor was chosen from them; it fails when a metric gets
worse, when the number of scored documents changes, or when any document that was handled
correctly no longer is.

**Limits of this set:** one model, one prompt template, one run, 45 scored documents from a
single facts file; the errors are ones the model was asked to make, which are easier than the
ones it makes by accident. It shows the checks work on model-written prose, not how often a
model errs unprompted.

### Pair corpus

`evals/pairs/cases.jsonl` holds 52 hand-written pairs (30 Dutch, 22 Arabic), built by
`evals/pairs/build_cases.py`: 14 clean pairs, 29 pairs that are a clean target with exactly one
planted error, and 9 hard cases written to show a known limit. The planted errors are a changed
number, a number left in the source's format, a dropped number, an added number, a percentage
that lost its sign, a translated name, a missing term, a forbidden phrase, a missing required
line and the wrong form of address.

| | cases | handled as intended |
|---|---|---|
| clean pairs | 14 | 14 pass |
| planted errors | 29 | 29 fail on the planted rule |
| hard cases | 9 | 0 (3 errors pass, 6 clean pairs fail) |

Counting the hard cases, the catch rate is 0.906 and the false-alarm rate 0.3. The floors in
`evals/pairs/gate.json` were written after the dev split and before the test split was run, and
the baseline pins every single outcome, so a new miss or false alarm fails `make check`.

This set was written together with the checker. It is a regression gate and a description of
behaviour, not an accuracy estimate. Neither the Dutch nor the Arabic has been checked by a
native speaker yet.

### Localisation experiment

The question: when a model localises English copy, how often does it break a market rule, does
putting the rules in the prompt help, and how much of what is left does the gate catch?

`evals/l10n/` holds 40 short English texts in a fictional world, written by the author, each
with numbers and some of the brand file's names and terms. `gemini-3.6-flash` (Vertex AI,
thinking level low, 2026-11-11) localised each into Dutch and Arabic under two prompts: `rules`
contains the market's section of the brand file, `bare` does not. That is 160 documents. The
sources were split into `dev` and `test` (20 each) before anything was run.

Every document was labelled by reading it before the checker ran on its half: which of the six
rules a reviewer would say it breaks, with the evidence. The labels were written by the coding
agent that built this version (Claude). They have not yet been reviewed by a second reader.
Labels record each document's SHA-256, the raw API responses are kept, and
the history shows each half's labels committed before the commit that ran the checker on it.
The notes in `make_labels.py` record, before each run, where the reader expected the checker
to disagree.

**What the model did** (from the labels, 40 documents per row):

| Market | Prompt | Breaks a rule other than the required line | Term | Address | Name | Number | Forbidden |
|---|---|---|---|---|---|---|---|
| Dutch | bare | 15 of 40 | 8 | 9 | 0 | 0 | 0 |
| Dutch | rules | 0 of 40 | 0 | 0 | 0 | 0 | 0 |
| Arabic | bare | 12 of 40 | 8 | n/a | 4 | 0 | 0 |
| Arabic | rules | 0 of 40 | 0 | n/a | 0 | 0 | 0 |

Without the rules, the model chose its own word for a brand term (`klantenportaal`,
`bezorgmoment`, `الناقل`), addressed the Dutch reader with "u", and four times added an Arabic
transliteration next to a name. It never broke a number. With the rules in the prompt it broke
none of the six rules in 80 documents. The `bare` documents all lack the required line, because
the model was never given it; that is not counted above.

**What the gate did against the labels:**

| Half | Documents | Same rules as the label | Violations reported, required line aside | Documents with a false alarm |
|---|---|---|---|---|
| dev, first run | 80 | 67 | 13 of 15 | 11 |
| dev, after tuning on it | 80 | 77 | 13 of 15 | 1 |
| **test, run once** | 80 | **70** | **12 of 14** | **8** |
| test, after one fix found on it | 80 | 72 | 12 of 14 | 6 |

The missing required line was reported in all 40 `bare` documents of each half.

The row to read is `test, run once`. On it the gate reported every labelled term, address and
required-line violation, and missed both name violations. Its 8 false alarms:

- 2 Dutch clock times ("4 pm" written as `16.00 uur` and `16:00 uur`);
- 2 Dutch compounds that contain the brand's word (`zendingsgeschiedenis`, `zendinghistorie`);
- 1 Arabic "one" written as a word without a scale word, and 1 dual noun that is not listed
  (`شخصين`, two people);
- 2 documents where `الاثنين` (Monday, in "Monday to Saturday") was read as the number two.

Three of the 8 are in the `rules` half, which is the text a reviewer would really receive: 3 of
40 clean documents failed. The Monday reading was a defect, not a known limit, and was fixed
after the run (the masculine forms of "two" no longer take the article); the last row shows the
result and is not a blind number. The other six are limits listed below. The two misses are the
transliteration written next to a kept name, also listed below.

One thing the six rules do not cover at all: one Arabic `rules` document contains two Hebrew
letters inside an Arabic word. It passes.

**What these numbers are not.** One model, one prompt per condition, one run, 40 short texts in
one invented domain, labelled by the agent that wrote the checker. They describe this run. They
do not estimate how often models break brand rules, and the dev rows are tuned on. From here on
both halves are a regression set: `make check` fails when a document's outcome changes.

## Design in short

- **Deterministic and explainable.** Every finding has a line, a column and a reason; every
  pass has a trace to a fact. No model call, no network, same result every run.
- **Context, not just values.** A value check alone passes a true number attached to the wrong
  claim, which is the most common way an edited draft goes wrong.
- **Fail closed.** Every digit run is a claim unless a documented skip rule says otherwise.
  Invalid facts files (duplicate ids or keys, missing sources, unknown keys) are rejected;
  unreadable, non-UTF-8 or oversized input exits 2, never "pass".
- More in [`docs/DESIGN.md`](docs/DESIGN.md).

## Limits

### Single-document check

- English only. Number words, stopwords and the stemmer are English, and a European decimal
  comma (`1,5`) is not read, so that number is not checked. Dutch and Arabic are read only by
  the pair check, as targets.
- ISO dates are read as separate numbers (`2021-03-05` gives 2021, 3 and 5), each needing a fact.
- Every line break ends a sentence, so in hard-wrapped prose a number near the end of a line
  loses the context words on the next line (a false alarm, never a false pass).
- "two hundred and fifty" is read as 200 and 50; "half a million" as one million.
- `$` alone and "dollars" alone are read as US dollars, so "$5" does not match a fact in
  Canadian dollars (a false alarm, never a false pass). Currency words outside the built-in list
  are not recognised: such an amount is read as a plain number, which may match money in any
  currency.
- Relations between facts are not checked. A model writing from facts linked them with a time,
  cause or employer the facts do not state in all 24 clean documents of the model-written set
  ("these improvements raised satisfaction"); every one passes.
- Meaning is not understood: a number used with the right topic words but the wrong meaning
  passes (see the hard cases). The checker narrows what a reviewer must read; it does not
  replace the review.
- Rounding and qualifiers are not interpreted: "nearly 20%" against a fact of 18% fails.
- Only recognised skill terms are checked; a tool missing from the vocabulary (such as "Excel",
  missed twice in the model-written set) is not caught unless added to `vocabulary`.
  Case-sensitive short terms are missed in lower case.
- `5m` is read as 5 million; a document about metres needs a different unit.
- Version numbers with one dot (`Python 3.12`) are numbers and need a fact.

### Pair check

- It does not judge whether a translation is fluent, natural or faithful in meaning. "An
  increase of 15%" translated as "a decrease of 15%" passes: the number is the same. Two
  numbers swapped between two nouns pass too.
- It checks tone only where tone is a rule a list can express: forbidden phrases, and the form
  of address in Dutch.
- English source; Dutch and Arabic targets. No other language. The Dutch word lists and the
  Dutch test pairs have not been checked by a native speaker. The Arabic word lists and test
  pairs were drafted by the coding agent and have not yet been reviewed by a native speaker.
- A term is checked for presence, not per occurrence: if the source says "shipment" twice and
  the target uses the brand's word once and another word the second time, it passes.
- Terms and forbidden phrases match by listed forms. A Dutch compound (`zendingnummer`) or an
  inflected form that is not listed is reported as a missing term (a false alarm), and an
  inflected forbidden phrase (`gratis verzenden` for `gratis verzending`) passes (a miss).
- A name must occur as often as in the source, so a name replaced by a pronoun the second time
  is reported (a false alarm). A transliteration written next to a kept name
  (`إكزامبل فريت (ExampleFreight)`) passes (a miss): list the transliteration under `forbidden`.
- A spelled-out number outside the word lists is not read, and the source's number is then
  reported as missing (a false alarm): long Dutch compounds (`driehonderdvijftig`), Arabic
  hundreds written as one word, and an Arabic dual noun that is not in the list.
- A clock time written the local way ("6 pm" as `18.00 uur`, "8" as `08:00`) is reported as a
  changed or missing number (a false alarm).
- A currency converted during localisation (US dollars to euros) is reported as a changed
  number.
- Month names are not read as numbers, and slashed dates are skipped on both sides, so a changed
  month passes.
- It does not detect a paragraph left untranslated.
- An Arabic suffix that changes a word's spelling (`بوابة عملائنا` for `بوابة العملاء`) is
  reported as a missing term (a false alarm).

## License

Apache-2.0, see [LICENSE](LICENSE). Copyright 2026 Hossam Afifi.
