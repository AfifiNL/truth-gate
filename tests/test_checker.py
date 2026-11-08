from __future__ import annotations

from pathlib import Path

from conftest import ROOT, fact, make_checker
from truth_gate.checker import Checker
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


def test_findings_point_at_line_and_column(tmp_path: Path) -> None:
    c = make_checker([fact("t", "Led a team of 12 engineers.")])
    report = c.check("# Title\n\nRobin led 13 engineers.")
    f = report.findings[0]
    assert (f.line, f.column, f.text) == (3, 11, "13")
