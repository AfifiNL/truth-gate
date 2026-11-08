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
3. the number's own **clause** (bounded by `, ; :`, brackets or a spaced dash) does not match a
   fact *without* this number by `misplaced_margin` (2) or more words than it matches the best
   fact *with* it. This catches a true number moved to another claim when the two claims share
   a topic word: "reduced first-response time for support tickets from 26 hours to 9 hours"
   shares "support" with the fact about a team of 9, but five words with the response-time
   fact.

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
0.75, the false-alarm rate exceeds 0.20, or any metric gets worse than in
`evals/baseline.json` (an improvement passes; re-record the baseline to lock it in). Tests prove the gate works: a checker that skips numbers, ignores context
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
prompt sets everything in a fictional world; no real company, place or person appears (a test
checks every capitalised word). `evals/llm/generate.py` regenerates the set and costs about 48
model calls; it refuses to make any call unless `TG_MAX_LIVE_CALLS` is set.

Every document was **labelled by reading it before the checker was run on any of them**
(`evals/llm/labels.jsonl`, one reason per document). Generated text is never edited:
`tests/test_llm_eval.py` checks each document's hash and, without using truth-gate's parser,
that each label's evidence holds (an injected number is absent from the facts, an invented tool
is absent from the facts file, a clean document uses no digit string the facts lack).

What the model did:

- **Injected errors: 22 of 24 followed the instruction.** Wrong number 6/6, invented tool 6/6,
  blocked phrase 6/6, moved number 4/6. One "moved" number became "4 million" hours (a changed
  value), and one swapped two numbers instead of moving one; both are dropped from the scores.
  For the blocked phrase it chose "rockstar" all six times; the invented tools were Tableau (2),
  Excel (2), Salesforce and Docker.
- **Clean documents: 24 of 24 used only figures, tools and phrases from the facts.** But all 24
  also linked facts with a relation the facts do not state: a time ("during this period"), a
  cause ("these improvements raised satisfaction") or an employer ("at ExampleParcel Co,
  Jordan raised the score"). truth-gate does not check relations, so these pass.

Scores (46 scored documents; a split was fixed before generation, `heldout` was run once after
the checker was frozen):

| scope | documents | catch rate | false-alarm rate | wrong number | moved number | invented tool | blocked phrase |
|---|---|---|---|---|---|---|---|
| all | 46 | 0.909 | 0.000 | 1.000 | 1.000 | 0.667 | 1.000 |
| dev | 22 | 0.900 | 0.000 | 1.000 | 1.000 | 0.667 | 1.000 |
| heldout | 24 | 0.917 | 0.000 | 1.000 | 1.000 | 0.667 | 1.000 |

Both misses are "Excel", which is not in the built-in vocabulary ("excel" is also an English
verb). It was deliberately not added after the dev run, because the held-out half uses it too.
One checker change was made after looking at `dev`: rule 3 above (moved numbers), which caught
one dev document the overlap rule passed. On `heldout`, the overlap rule alone already caught
all three moved numbers, so the new rule changed nothing there, and it added no false alarm on
either set. Its evidence is one dev document plus "no harm" on the held-out half and the
hand-built set, not a measured improvement. `make eval` gates this set on its baseline only:
the results were seen after the fact, so no floor was chosen from them.

**Limits of this set:** one model, one prompt template, one run, 46 scored documents from a
single facts file; the errors are ones the model was asked to make, which are easier than the
ones it makes by accident. It shows the checks work on model-written prose, not how often a
model errs unprompted.

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

- English only. Number words, stopwords and the stemmer are English. A European decimal comma
  (`1,5`) is not read at all, so that number is not checked.
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

## License

Apache-2.0, see [LICENSE](LICENSE). Copyright 2026 Hossam Afifi.
