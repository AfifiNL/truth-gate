from __future__ import annotations

import pytest

from conftest import ROOT, fact, make_checker
from truth_gate.checker import MAX_DOCUMENT_CHARS, Checker, DocumentTooLarge
from truth_gate.facts import Facts


def errors(report_checks: list[tuple[str, str]], check: str) -> int:
    return sum(1 for c, sev in report_checks if c == check and sev == "error")


def run(checker: Checker, text: str) -> list[tuple[str, str]]:
    return [(f.check, f.severity) for f in checker.check(text).findings]


def test_examples_pass_and_fail_for_the_documented_reasons(example_facts: Facts) -> None:
    checker = Checker(example_facts)
    ok = checker.check((ROOT / "examples" / "pass.md").read_text(encoding="utf-8"))
    assert ok.passed
    assert ok.errors == 0
    assert ok.warnings == 0
    assert {t.fact_id for t in ok.traces} >= {"team-lead", "cloud-costs", "migration", "budget"}
    bad = checker.check((ROOT / "examples" / "fail.md").read_text(encoding="utf-8"))
    assert not bad.passed
    got = {(f.check, f.text) for f in bad.findings if f.severity == "error"}
    assert got == {
        ("number", "15"),
        ("blocked", "guaranteed results"),
        ("skill", "Kafka"),
        ("number", "12"),
    }
    assert {f.text for f in bad.findings if f.severity == "warning"} == {"seamless", "cutting-edge"}


def test_number_needs_a_fact_and_a_shared_context() -> None:
    c = make_checker([fact("t", "Led a team of 12 engineers.")])
    assert c.check("Robin led 12 engineers.").passed
    out_of_context = c.check("Robin has 12 years of experience.")
    assert not out_of_context.passed
    assert out_of_context.findings[0].fact_ids == ["t"]
    assert "out of context" in out_of_context.findings[0].message
    missing = c.check("Robin led 13 engineers.")
    assert "does not appear in any fact" in missing.findings[0].message


def test_context_is_limited_to_the_sentence_and_the_window() -> None:
    c = make_checker([fact("t", "Led a team of 12 engineers.")], context_window=3)
    # The shared word sits in the previous sentence: not evidence.
    assert not c.check("Engineers matter. Robin has 12 cats.").passed
    # Shared word more than 3 words away: outside the window.
    assert not c.check("Engineers were not the point when Robin bought 12 cats.").passed
    assert c.check("Robin hired 12 engineers.").passed


def test_subject_name_is_not_shared_context() -> None:
    c = make_checker([fact("t", "Robin Example led a team of 12 engineers.")])
    assert not c.check("Robin Example owns 12 bikes.").passed


def test_min_context_overlap_is_configurable() -> None:
    c = make_checker([fact("t", "Led a team of 12 engineers.")], min_context_overlap=2)
    assert not c.check("Robin hired 12 engineers.").passed
    assert c.check("Robin led a team of 12 engineers.").passed


def test_extra_numbers_and_currency_rules() -> None:
    facts = [
        {
            "id": "b",
            "text": "Managed the platform budget.",
            "source": "s",
            "numbers": [{"value": 1200000, "unit": "EUR"}],
        },
    ]
    c = make_checker(facts)
    assert c.check("Managed a platform budget of €1.2m.").passed
    assert c.check("Managed a platform budget of 1.2 million.").passed  # currency omitted
    assert not c.check("Managed a platform budget of $1.2m.").passed  # wrong currency


def test_skills_aliases_fact_text_terms_and_unlisted_terms() -> None:
    c = make_checker(
        [fact("m", "Migrated services from MySQL to PostgreSQL.")],
        skills=[{"name": "Postgres"}, "Python"],
    )
    # 'Postgres' in the facts allows 'PostgreSQL' in the document (same canonical skill);
    # MySQL is named in a fact, so mentioning it is not an invented claim.
    assert c.check("Uses PostgreSQL, MySQL and Python.").passed
    report = c.check("Runs K8s and Apache Spark.")
    assert {f.text for f in report.findings} == {"K8s", "Apache Spark"}
    # Case-sensitive short terms: the verb 'react' is not the library.
    assert c.check("Teams react quickly.").passed
    assert not c.check("Built a React app.").passed


def test_blocked_phrases_ignore_case_and_whitespace_but_need_whole_words() -> None:
    c = make_checker(
        [fact("f", "Wrote code.")], blocked_phrases=["world-class", "guaranteed results"]
    )
    assert errors(run(c, "A World-Class team."), "blocked") == 1
    assert errors(run(c, "It delivers guaranteed\n results."), "blocked") == 1
    assert errors(run(c, "worldclass"), "blocked") == 0


def test_tone_phrases_warn_but_never_fail() -> None:
    c = make_checker([fact("f", "Wrote code.")])
    report = c.check("I delve into seamless synergies.")
    assert report.passed
    assert report.warnings == 3
    custom = make_checker([fact("f", "Wrote code.")], tone_phrases=["delve"])
    assert custom.check("I delve into seamless synergies.").warnings == 1


def test_findings_point_at_line_and_column() -> None:
    c = make_checker([fact("t", "Led a team of 12 engineers.")])
    report = c.check("# Title\n\nRobin led 13 engineers.")
    f = report.findings[0]
    assert (f.line, f.column, f.text) == (3, 11, "13")


def test_context_does_not_leak_across_lines_or_list_items() -> None:
    c = make_checker([fact("t", "Led a team of 12 engineers.")])
    assert not c.check("1. Hired engineers\n2. Owns 12 cats").passed
    assert not c.check("Hired engineers\nOwns 12 cats").passed
    assert c.check("1. Hired 12 engineers").passed


def test_a_wrapped_line_starting_with_a_number_is_checked() -> None:
    c = make_checker([fact("t", "Led a team of 12 engineers.")])
    report = c.check("Robin's team grew from 12 engineers to\n40. That was the plan.")
    assert [f.text for f in report.findings] == ["40"]


def test_currency_and_scale_mismatches_fail() -> None:
    c = make_checker([fact("b", "Managed a platform budget of €1.2 million.")])
    assert c.check("Managed a platform budget of €1.2m.").passed
    for wrong in ("CHF 1.2 million", "US$1.2m", "1.2 million CAD", "€1.2 billion"):
        assert not c.check(f"Managed a platform budget of {wrong}.").passed, wrong
    users = make_checker([fact("u", "Served 3 regional user groups.")])
    assert not users.check("Served three million users in regional groups.").passed


def test_glued_units_need_the_same_unit_in_a_fact() -> None:
    c = make_checker([fact("p", "Made the report job 50x faster with 40GB less memory.")])
    assert c.check("The report job became 50x faster.").passed
    assert not c.check("The report job became 40x faster.").passed
    assert not c.check("The report job became 50ms faster.").passed


def test_skills_and_blocked_phrases_are_checked_inside_code_spans() -> None:
    c = make_checker([fact("f", "Wrote code.")], blocked_phrases=["guaranteed results"])
    report = c.check("We deliver `guaranteed results` with `Kafka`.")
    assert {(f.check, f.text) for f in report.findings} == {
        ("blocked", "guaranteed results"),
        ("skill", "Kafka"),
    }


def test_ambiguous_words_opening_a_sentence_only_warn() -> None:
    c = make_checker([fact("f", "Wrote code.")])
    for text in ("Swift responses matter.", "Spark joy in the team.", "- Go for it."):
        report = c.check(text)
        assert report.passed, text
        assert [f.severity for f in report.findings] == ["warning"], text
    report = c.check("Our go-to-market plan. Go-to-market matters.")
    assert [f for f in report.findings if f.check == "skill"] == []
    assert not c.check("We built it in Swift.").passed


def test_document_size_is_capped() -> None:
    c = make_checker([fact("f", "Wrote code.")])
    c.check("x" * MAX_DOCUMENT_CHARS)
    with pytest.raises(DocumentTooLarge, match="limit"):
        c.check("x" * (MAX_DOCUMENT_CHARS + 1))


def test_worst_case_document_at_the_cap_is_fast() -> None:
    import time

    c = make_checker([fact("t", "Led a team of 12 engineers.")])
    started = time.perf_counter()
    c.check(("12 engineers " * 20_000)[:MAX_DOCUMENT_CHARS])
    assert time.perf_counter() - started < 10.0


def test_a_number_moved_from_another_fact_is_flagged() -> None:
    facts = [
        fact("team", "Managed a support engineering team of 9 people."),
        fact("speed", "Reduced the average first-response time for support tickets to 4 hours."),
    ]
    c = make_checker(facts)
    moved = c.check("Reduced the average first-response time for support tickets to 9 hours.")
    assert not moved.passed
    assert "looks moved" in moved.findings[0].message
    assert moved.findings[0].fact_ids == ["team"]
    # Two facts joined in one sentence: each number is judged within its own clause.
    joined = (
        "Managed a support engineering team of 9 people, "
        "and reduced first-response time to 4 hours."
    )
    assert c.check(joined).passed
    # misplaced_margin: 0 switches the rule off (the shared word "support" then suffices).
    off = make_checker(facts, misplaced_margin=0)
    assert off.check(
        "Reduced the average first-response time for support tickets to 9 hours."
    ).passed


def test_two_facts_joined_by_and_are_judged_separately() -> None:
    c = make_checker(
        [
            fact("routing", "Automated 35% of incoming ticket routing with Python and Zapier."),
            fact("help", "Wrote 60 help-centre articles that cut repeat questions by 22%."),
        ]
    )
    for text in (
        "Automated 35% of routing and wrote 60 help-centre articles that cut repeat questions "
        "by 22%.",
        "Wrote 60 articles and automated 35% of incoming ticket routing with Python and Zapier.",
    ):
        report = c.check(text)
        assert report.passed, (text, [f.message for f in report.findings])


def test_clause_level_comparison_is_what_keeps_a_joined_sentence_passing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = [
        fact("degree", "BA in Economics, University of Sampleton, 2014."),
        fact("help", "Wrote 60 help-centre articles that cut repeat questions by 22%."),
    ]
    text = (
        "Holding a BA in Economics from the University of Sampleton in 2014, Robin wrote 60 "
        "help-centre articles that cut repeat questions by 22%."
    )
    assert make_checker(facts).check(text).passed
    # The same rule applied to the whole sentence instead of the clause flags 2014.
    monkeypatch.setattr(
        Checker,
        "_clause_words",
        lambda self, breaks, words, starts, sentence, q: self._window(words, starts, sentence, q),
    )
    report = make_checker(facts).check(text)
    assert [f.text for f in report.findings] == ["2014"]


def test_worst_case_with_many_facts_is_fast() -> None:
    import time

    facts = [
        fact(f"f{i}", f"Led a support team of {i} engineers in region {i} for project {i}.")
        for i in range(1, 301)
    ]
    c = make_checker(facts)
    doc = "".join(
        f"Led a support team of {i % 300 + 1} engineers and moved {(i * 7) % 300 + 1} "
        f"parcels for region {i}. "
        for i in range(20_000)
    )[:MAX_DOCUMENT_CHARS]
    started = time.perf_counter()
    c.check(doc)
    assert time.perf_counter() - started < 15.0
