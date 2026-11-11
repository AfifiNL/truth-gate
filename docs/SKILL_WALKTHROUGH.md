# Skill walk-through

One session, recorded on 2026-11-11. An agent (Claude Code, as a subagent with no other context)
was pointed at [`skills/localisation-check/SKILL.md`](../skills/localisation-check/SKILL.md)
and given a failing Dutch draft, [`examples/pair/fail.nl.md`](../examples/pair/fail.nl.md), to
repair. It was told to follow the skill and nothing else, to work on a copy, and to report every
command with its output. The skill did not load by itself: the agent was told where the file
was.

Commands and outputs are as the agent reported them. Paths are shortened to repository-relative
ones and `<copy>/draft.nl.md`, and the `uv run` prefix is left out. The two check outputs were
reproduced afterwards on the agent's files and match.

## The session

**1. Validate the brand file** (the skill's "Before you write", step 2)

```text
$ truth-gate brand examples/pair/brand.yaml
OK: ExampleFreight, 2 name(s) that stay as written, 2 market(s)
  nl-NL: 2 term(s), 2 forbidden phrase(s), 1 required line(s), address informal
  ar: 2 term(s), 1 forbidden phrase(s), 1 required line(s)
```

**2. Check the draft as received**

```text
$ truth-gate check-pair <copy>/draft.nl.md --source examples/pair/source.en.md \
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
exit code: 1
```

**3. What the agent changed**, in its own words:

- Name: the heading "Volgbord" became "TrackBoard", because it is a `do_not_translate` name.
- Term: "vrachten" became "zendingen", and "uw pakketten" became "elke zending" (the source says
  "every shipment"). The second change also removes the formal "uw".
- Numbers: "1,200" became "1.200" and "98.5%" became "98,5%". "twintig" became "twaalf" because
  the source says twelve.
- Forbidden phrase: ", met gratis verzending" was removed. It is forbidden and is not in the
  source, so this is not deleting a source sentence.
- Required line: "Prijzen zijn exclusief btw." was added as its own closing paragraph.
- Not prompted by a finding: "tot twaalf personen" became "van maximaal twaalf personen",
  because "tot" can read as excluding twelve and the source says "up to twelve".

**4. Check again**

```text
$ truth-gate check-pair <copy>/draft.nl.md --source examples/pair/source.en.md \
      --brand examples/pair/brand.yaml --market nl-NL
PASS (nl-NL): 0 error(s), 0 warning(s); 5 number(s) in the source, 5 in the target
exit code: 0
```

**5. The draft it handed over**

```markdown
# TrackBoard voor groeiende teams

ExampleFreight verwerkte in 2024 1.200 zendingen per dag, en 98,5% kwam op tijd aan.

Open het klantportaal om elke zending te volgen. TrackBoard-abonnementen beginnen bij € 49
per maand, voor teams van maximaal twaalf personen.

Prijzen zijn exclusief btw.
```

With it, as the skill asks, one line on what it was unsure about: it kept the colleague's
"verwerkte" (processed) for the source's "moved", where "vervoerde" would be closer, and left
that and its own "van maximaal twaalf" wording to the reviewer, "since the check does not judge
meaning".

## What the session showed about the skill

The agent was asked to say where the skill was unclear or did not match the tool. It named
seven places, and the skill was changed for each after the session:

1. The skill said every finding has a line and column. The required-line finding has none.
2. The skill said to use the term "wherever" the source does. The check reports a term only
   when no listed form appears at all, so a second "shipment" translated as "pakketten" would
   have passed.
3. `vracht` is forbidden, and "vrachten" in the draft produced no forbidden finding. The skill
   did not say that only the listed phrase is found.
4. The skill forbade deleting a sentence that is in the source. It did not say what to do with
   draft text that is not in the source.
5. The skill assumed the agent was the author. Nothing covered repairing someone else's draft.
6. "Keep every number" did not say that a number written as a word counts.
7. The skill showed a bare `truth-gate` command. In this repository it runs as
   `uv run truth-gate`.

Points 2 and 3 are limits of the check, not only of the skill's wording. They are listed under
Limits in the README.

## What this is not

One session, one draft, Dutch only, and a draft written to fail. It shows the loop the skill
describes (check, fix, check again, hand over with the report) running once. It is not a
measure of how well an agent localises.
