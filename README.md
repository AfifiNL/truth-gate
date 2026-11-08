# truth-gate

A deterministic check for AI-written documents (a CV, a cover letter, a report, a product
page) against a **facts file** you control:

- every **number** in the document must equal a number in a fact **and** be used in that fact's
  context (a true "12" from "a team of 12 engineers" does not license "12 years of experience");
- every **skill or tool** the document names must be listed in the facts file;
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
    3: 2019 <- team-lead (engineer, freight, lakeside, ltd, team)
    3: 2023 <- team-lead (engineer, freight, lakeside, ltd)
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
    text: Led a team of 12 engineers at Lakeside Freight Ltd from 2019 to 2023.
    source: employment reference letter, Lakeside Freight Ltd, 2023   # where a reviewer checks it
  - id: budget
    text: Managed a platform budget of €1.2 million per year.
    source: budget approval e-mail, 2022
    numbers: []                 # optional: numbers the text does not spell out ({value, unit})
skills:
  - Python
  - name: PostgreSQL
    aliases: [Postgres]
blocked_phrases: [guaranteed results, world-class]
# optional: vocabulary (extra terms to recognise), tone_phrases (replaces the built-in list),
# min_context_overlap (default 1), context_window (default 8 words)
```

Numbers are read from each fact's text, so a fact is written once, in plain words. Unknown keys
are rejected, so a typo cannot silently switch a check off.

## The rules, exactly

**Numbers.** Integers, decimals, thousands separators, percentages (`%`, "percent", "per
cent"), money (`€ $ £`, `EUR USD GBP`, "euros"), scales (`k`, `m`, `bn`, "thousand", "million"),
ranges (`10–15%`, `€2–3m`: the unit applies to both ends), ordinals and written-out numbers from
two to ninety-nine. A document number passes when:

1. some fact contains an equal quantity: same value; a percentage only matches a percentage;
   money only matches money in the same currency; a plain number may match money (leaving out
   the currency is not a false claim); and
2. at least `min_context_overlap` content words within `context_window` words either side of the
   number, **in the same sentence**, also appear in that fact's text. Content words are stemmed
   lightly ("conferences" = "conference"), and stopwords, units ("years", "months"), numbers and
   the subject's name are ignored.

Not read as numbers: code spans and fenced code, URLs and link targets, ordered-list markers,
version strings with two or more dots (`3.12.1`), times (`10:30`), numbers joined by a slash
(`24/7`, `03/2021`), word-hyphen-number names (`COVID-19`), and the word "one" ("one of the
reasons"). Anything in this list is **not checked**, so a false figure written that way passes.

**Skills.** 110 built-in tool and skill entries, with aliases, (`src/truth_gate/data/skills.txt`) plus the
facts file's skills and `vocabulary`, matched as whole terms, longest first, with aliases mapped
to one name (`K8s` → Kubernetes). Short or ambiguous terms are case-sensitive (`Go`, `R`,
`React`, `Spark`, `Helm`), so "teams react quickly" is not a claim about a library. A term
passes if it is a listed skill or appears in a fact's text (a fact that says "from MySQL to
PostgreSQL" makes mentioning MySQL true).

**Blocked phrases** match case-insensitively as whole phrases, across line breaks. **Tone**
phrases (`src/truth_gate/data/tone.txt`) are warnings only; `--strict` makes them fail.

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

`evals/cases.jsonl` holds 34 synthetic documents about a fictional person (`evals/facts.yaml`,
different from the examples), built deterministically by `evals/build_cases.py` from
hand-written sentences: 10 clean documents and 24 with exactly one injected error (wrong number,
number out of context, invented skill, blocked phrase). Five cases are marked `hard`: they were
written to show known weaknesses and are expected to be missed. Split: alternate cases go to
`dev` and `test`.

- **catch rate**: share of error documents that fail **for the injected reason** (a wrong
  number must fail on a number finding, not on a stray tone hit);
- **false-alarm rate**: share of clean documents that fail.

Results of `make eval` (deterministic, so these are exact):

| scope | cases | catch rate | false-alarm rate | wrong number | out of context | invented skill | blocked phrase |
|---|---|---|---|---|---|---|---|
| all | 34 | 0.833 | 0.100 | 1.000 | 0.714 | 0.833 | 0.800 |
| dev | 17 | 0.833 | 0.000 | 1.000 | 0.750 | 0.667 | 1.000 |
| test | 17 | 0.833 | 0.200 | 1.000 | 0.667 | 1.000 | 0.667 |

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
0.75, the false-alarm rate exceeds 0.20, or any metric moves the wrong way against
`evals/baseline.json`. Tests prove the gate works: a checker that skips numbers, ignores context
or ignores skills fails it.

**What these numbers are not.** The corpus was written by the same author as the checker, from
the same rules; it is a regression gate and a description of behaviour, not an accuracy
estimate for real AI-written documents.

## Design in short

- **Deterministic and explainable.** Every finding has a line, a column and a reason; every
  pass has a trace to a fact. No model call, no network, same result every run.
- **Context, not just values.** A value check alone passes a true number attached to the wrong
  claim, which is the most common way an edited draft goes wrong.
- **Fail closed on input.** Invalid facts files (duplicate ids, missing sources, unknown keys)
  are rejected; unreadable input exits 2, never "pass".
- More in [`docs/DESIGN.md`](docs/DESIGN.md).

## Limits

- English only. Number words, stopwords and the stemmer are English. A European decimal comma
  (`1,5`) is not read at all, so that number is not checked.
- ISO dates are read as separate numbers (`2021-03-05` gives 2021, 3 and 5), each needing a fact.
- Meaning is not understood: a number used with the right topic words but the wrong meaning
  passes (see the hard cases). The checker narrows what a reviewer must read; it does not
  replace the review.
- Rounding and qualifiers are not interpreted: "nearly 20%" against a fact of 18% fails.
- Only recognised skill terms are checked; a tool missing from the vocabulary is not caught
  unless added to `vocabulary`. Case-sensitive short terms are missed in lower case.
- `5m` is read as 5 million; a document about metres needs a different unit.
- Version numbers with one dot (`Python 3.12`) are numbers and need a fact.

## License

Apache-2.0, see [LICENSE](LICENSE). Copyright 2026 Hossam Afifi.
