# truth-gate v0.2: spec

Written on 2026-11-11, before any v0.2 code. Where the build ends up different, the difference and
its reason are in [DESIGN.md](DESIGN.md).

## 1. What v0.2 adds

truth-gate v0.1 checks one English document against a facts file. v0.2 adds a second check for
localised content: a translated or localised draft is checked against its English source and
against a brand file that holds the rules for one market. The check is deterministic. No model
is involved, and the same three files always give the same report.

Truth flows one way: facts → English source → localised target. The source is checked against the
facts with the v0.1 rules. The target is checked against the source and the market's rules. The
target is never checked against the facts directly, because the facts are English sentences and
the context rule compares English words.

v0.2 also ships an agent skill and a second MCP tool, so an agent that localises a document runs
the check itself before a person reviews the draft.

## 2. What it does not do

These go into the README as written.

- It does not judge whether a translation is fluent, natural or faithful in meaning. "An increase
  of 15%" translated as "a decrease of 15%" passes: the number is the same.
- It checks tone only where tone is a rule a list can express: forbidden phrases, and the form of
  address in Dutch.
- English source; Dutch and Arabic targets. No other language.
- Terms match by listed forms. An inflected form that is not listed is reported as a missing term
  (a false alarm, never a false pass).
- A spelled-out number outside the built-in word lists is not read. If the source has the digits,
  the target is reported as missing that number (a false alarm).
- A currency converted during localisation (US dollars to euros) is reported as a changed number.
- Month names are not read as numbers, and slashed dates are skipped on both sides, so a changed
  month passes.
- It does not detect a paragraph left untranslated.

## 3. The brand file

One YAML file per brand. Unknown keys and duplicate keys are rejected, as in the facts file, so a
typo cannot switch a rule off.

```yaml
brand: ExampleFreight
source_locale: en
do_not_translate: [ExampleFreight, TrackBoard]     # must appear unchanged in every target
markets:
  nl-NL:
    address: informal            # informal: "u" and "uw" fail. formal: "je", "jij", "jouw" fail.
    terms:
      - source: shipment
        target: [zending, zendingen]
      - source: customer portal
        target: [klantportaal]
    forbidden: [vracht, gratis verzending]
    required_lines:
      - "Prijzen zijn exclusief btw."
  ar:
    terms:
      - source: shipment
        target: ["شحنة", "شحنات"]
    forbidden: []
    required_lines: []
```

All example content is fictional.

## 4. The pair check

```text
truth-gate check-pair target.nl.md --source source.en.md --brand brand.yaml --market nl-NL
                      [--facts facts.yaml] [--json] [--strict]
```

With `--facts`, the source is first checked with the v0.1 rules, and a failing source fails the
pair. Exit codes as in v0.1: 0 pass, 1 fail, 2 unreadable or oversized input, or an unknown market.

Six rules, each reported with line, column, rule name and reason:

1. **Number parity.** Every quantity in the source must appear in the target with the same value
   and kind (plain, percent, currency, unit), and the target must not contain a quantity the
   source lacks. Quantities are compared as a multiset over the whole document. When source and
   target have the same number of paragraphs, a finding also names the paragraph.
2. **Do-not-translate names.** Each name must occur in the target exactly as written, at least as
   often as in the source.
3. **Terms.** When the source contains a `source` term, the target must contain one of its
   `target` forms.
4. **Forbidden phrases.** Any `forbidden` phrase in the target fails, matched as a whole phrase.
5. **Required lines.** Each `required_lines` entry must appear in the target, compared after
   collapsing whitespace.
6. **Form of address** (Dutch only, when `address` is set). The pronouns of the other register
   fail.

Masking is as in v0.1: numbers inside code, comments, URLs and link targets are not read. The
other rules run on the whole text.

## 5. Reading numbers per locale

The v0.1 scanner gains a `locale` argument. English stays the default and its behaviour does not
change.

| | English | Dutch | Arabic |
|---|---|---|---|
| Decimal mark | `.` | `,` | `.` or `٫` |
| Thousands mark | `,` | `.` or a space, in groups of three | `,` or `٬` |
| Digits | `0-9` | `0-9` | `0-9` and `٠-٩` |
| Percent | `%`, percent | `%`, procent | `%`, `٪`, and the listed words |
| Scale words | thousand, million, billion | duizend, miljoen, miljard | the listed words |
| Number words | as v0.1 | een to twintig, the tens, honderd | one to ten, in the listed forms |

So `1,200` is one thousand two hundred in an English source and one point two in a Dutch target.
A Dutch draft that copies `1,200` from the source fails number parity, which is the error this
rule exists for. In a Dutch text, a dot that is not followed by exactly three digits (`1.5`) is
read as a decimal and reported as a warning: English number format in a Dutch text.

## 6. Matching Arabic text

Before any name, term, phrase or line is matched in Arabic, both sides are normalised:

- Unicode direction marks and isolates are removed, so a Latin brand name wrapped in them matches.
- Diacritics and the elongation character are removed.
- The alef forms are folded to one.
- For term matching only, one leading particle from a short fixed list (the conjunctions, the
  attached prepositions and the definite article) is stripped from each word.

The particle list and the folding rules are in one data file with a comment per line. They were
written by a native speaker. Every rule has a test with a word it should match and a word it must
not.

## 7. MCP tool and agent skill

`truth-gate serve --facts FILE --brand FILE` adds one tool:

- `check_localised(source_text, target_text, market)`: the pair report as structured content.
  Text only, never a path, as in v0.1.
- `list_facts()` gains the market's terms, forbidden phrases, required lines and names.

The repo ships `skills/localisation-check/SKILL.md`. It tells an agent that localises a document
to: read the market's section of the brand file first; write the draft; run the pair check; fix
every error and run it again; hand over the draft together with the passing report. It forbids
three things: editing the brand file, editing the source, and removing a sentence to make a
finding go away. The skill format is confirmed against the current Claude Code documentation at
build time.

`docs/SKILL_WALKTHROUGH.md` records one real session, dated, with the commands and their output:
a draft that fails, the fixes, and the pass.

## 8. Hand-built eval

`evals/pairs/`: source and target pairs in both markets. Clean pairs, and pairs with exactly one
planted error of a named type: a changed number, a number in the source's format, a dropped
number, a translated name, a missing term, a forbidden phrase, a missing required line, the wrong
form of address. `truth-gate eval` reports the catch rate per type and the false alarms on clean
pairs. Floors live in `evals/pairs/gate.json` and CI fails below them.

As in v0.1, the README says what this set is: written by the author of the checker, a regression
gate and a description of behaviour, not an accuracy estimate.

## 9. Model-written experiment

The question: when a model localises English copy, how often does it break a market rule, does
putting the rules in the prompt help, and how much of what is left does the gate catch?

- 40 short English source texts in a fictional world, generated and reviewed once, each using
  some of the brand file's names, terms and numbers.
- Each is localised by `gemini-3.6-flash` (Vertex AI) into Dutch and Arabic under two conditions:
  the prompt contains the market's rules, or it does not. 40 × 2 × 2 = 160 calls.
- Sources are split into `dev` (20) and `test` (20) before anything is run. Rules are tuned on
  `dev` only. `test` is run through the checker once.
- Every output is labelled by reading it, before the checker runs on any of them: which rules it
  breaks, with the evidence. Labels record each document's SHA-256. The README states who wrote
  the labels and who reviewed which share of them.
- The raw API responses are kept.
- `evals/l10n/generate.py` refuses to make any call unless a maximum call count is set.

Reported, per market and condition: the share of outputs that break at least one rule, by rule;
the gate's catch rate and false alarms against the labels; and the misses, listed. Whatever the
numbers are, they are published as measured. One run per condition is a small sample, and the
README says so.

## 10. Layout

New: `src/truth_gate/locales.py`, `brand.py`, `pair.py`, `data/nl.txt`, `data/ar.txt`,
`skills/localisation-check/SKILL.md`, `examples/pair/`, `evals/pairs/`, `evals/l10n/`,
`docs/SPEC-v0.2.md`, `docs/SKILL_WALKTHROUGH.md`.
Changed: `numbers.py` (locale argument), `cli.py`, `mcp_server.py`, `evals.py`, `README.md`,
`docs/DESIGN.md`, `Makefile` (`make check` also runs the pair gate and the replayed experiment).

## 11. Done means

1. This spec is committed before any v0.2 code, and what was built matches it, or the differences
   are listed in `docs/DESIGN.md` with reasons.
2. Every v0.1 test passes unchanged and both v0.1 eval gates give the same numbers as before.
3. `make check` passes locally and in CI from a fresh clone, offline.
4. The pair gate passes with its floors.
5. The experiment has been run once, `test` once, and its numbers are in the README with the
   misses.
6. The README's limits section contains every line of section 2, the "English only" and
   decimal-comma limits of v0.1 are rewritten to say what is now covered, and no number in the
   README comes from anywhere but a run.
7. The skill walk-through is recorded from a real session.
8. The secret and identifier scan is clean.
9. The author has walked through section 12.

## 12. What the author must be able to explain

1. Why the target is checked against the source and not against the facts.
2. How `1,200` is read in English and in Dutch, and which mistake that catches.
3. How Arabic text is normalised before matching, with one word the rules get wrong.
4. What the experiment measured, who labelled it, and what it does not prove.
5. What the skill tells an agent to do, and the three things it forbids.

## 13. Build order

| Day | Work |
|---|---|
| 1 | Locale number reading for Dutch and Arabic with tests; the brand file; number parity and do-not-translate names |
| 2 | Terms, forbidden phrases, required lines, form of address; CLI and MCP tool; the hand-built pairs and their gate; the skill |
| 3 | The experiment (dev, tuning, test once), labels and their review; README from real output; a fresh review; scan; walk-through |
