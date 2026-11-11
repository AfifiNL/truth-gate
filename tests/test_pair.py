"""The pair check: a localised draft against its English source and a market's rules."""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest
from mcp import Client

from conftest import ROOT
from truth_gate.brand import Brand, BrandError, load_brand, parse_brand
from truth_gate.checker import MAX_DOCUMENT_CHARS, DocumentTooLarge
from truth_gate.cli import main
from truth_gate.facts import Facts
from truth_gate.mcp_server import build_server
from truth_gate.pair import PairChecker, PairReport

PAIR = ROOT / "examples" / "pair"
BRAND = str(PAIR / "brand.yaml")
SOURCE = str(PAIR / "source.en.md")


@pytest.fixture
def brand() -> Brand:
    return load_brand(BRAND)


def raw_brand(**market: object) -> dict[str, object]:
    return {"brand": "ExampleFreight", "markets": {"nl-NL": market}}


def run(source: str, target: str, market: str = "nl-NL", **rules: object) -> PairReport:
    raw: dict[str, object] = {
        "brand": "ExampleFreight",
        "do_not_translate": rules.pop("names", []),
        "markets": {market: rules},
    }
    return PairChecker(parse_brand(raw), market).check(source, target)


def rules_hit(report: PairReport) -> list[str]:
    return [f.rule for f in report.findings if f.severity == "error"]


# --- numbers ---------------------------------------------------------------------------


def test_same_numbers_in_each_language_pass() -> None:
    source = "We moved 1,200 shipments in 2024; 98.5% arrived on time for €49."
    assert run(source, "In 2024 verwerkten we 1.200 zendingen; 98,5% was op tijd voor € 49.").passed
    arabic = "نقلنا ١٬٢٠٠ شحنة في 2024 ووصل %98.5 في الموعد مقابل 49 يورو."
    assert run(source, arabic, market="ar").passed


def test_a_number_copied_in_the_source_format_fails() -> None:
    report = run("We moved 1,200 shipments.", "We verwerkten 1,200 zendingen.")
    (finding,) = report.findings
    assert finding.rule == "number"
    assert finding.side == "target"
    assert "the source has 1200" in finding.message
    assert "decimal comma" in finding.message


def test_changed_dropped_and_added_numbers() -> None:
    changed = run("Teams of up to twelve people.", "Teams tot twintig personen.")
    assert rules_hit(changed) == ["number"]
    assert "the source has 12" in changed.findings[0].message
    dropped = run("Founded in 2019 with 40 people.", "Opgericht met 40 mensen.")
    (finding,) = dropped.findings
    assert (finding.side, finding.text) == ("source", "2019")
    assert "missing from the target" in finding.message
    added = run("Trusted by many teams.", "Vertrouwd door 500 teams.")
    assert "500 is not in the source" in added.findings[0].message


def test_a_percentage_must_stay_a_percentage() -> None:
    report = run("Costs fell by 20%.", "De kosten daalden met 20.")
    assert rules_hit(report) == ["number"]
    assert "the kind changed" in report.findings[0].message


def test_a_currency_or_unit_may_be_written_in_unknown_words() -> None:
    # "جنيه" is not in the currency list and "GB" is no longer glued: both become plain numbers.
    assert run("It costs £30 for 40GB.", "يكلف 30 جنيه مقابل 40 جيجابايت.", market="ar").passed
    assert not run("It costs €30.", "Het kost $ 30.").passed  # another currency is a change


def test_numbers_in_code_and_urls_are_not_compared() -> None:
    source = "Run `retry(3)` and see https://example.test/v2/2024 for 5 examples."
    assert run(
        source, "Voer `retry(3)` uit; zie https://example.test/v2/2024 voor 5 voorbeelden."
    ).passed


def test_english_number_format_in_dutch_is_a_warning() -> None:
    report = run("Growth of 1.5 times.", "Een groei van 1.5 keer.")
    assert report.passed
    assert [(f.rule, f.severity) for f in report.findings] == [("format", "warning")]


def test_meaning_is_not_checked() -> None:
    # A stated limit: the number is the same, the direction is reversed, and it passes.
    assert run("An increase of 15%.", "Een daling van 15%.").passed


# --- names, terms, phrases, lines, address -----------------------------------------------


def test_a_translated_name_fails_and_a_dutch_genitive_passes() -> None:
    source = "TrackBoard is new. Open TrackBoard today."
    report = run(source, "Volgbord is nieuw. Open TrackBoard vandaag.", names=["TrackBoard"])
    (finding,) = report.findings
    assert finding.rule == "name"
    assert "2 time(s) in the source, 1 in the target" in finding.message
    assert run(
        "ExampleFreight has a new portal.",
        "ExampleFreights nieuwe portaal is er.",
        names=["ExampleFreight"],
    ).passed


def test_a_latin_name_in_arabic_text_matches_through_marks_and_particles() -> None:
    source = "Use TrackBoard with ExampleFreight."
    target = "استخدم ‏TrackBoard‏ مع بـExampleFreight."
    assert run(source, target, market="ar", names=["TrackBoard", "ExampleFreight"]).passed


def test_terms_follow_the_source() -> None:
    terms = [{"source": "shipment", "target": ["zending", "zendingen"]}]
    assert run("Track every shipment.", "Volg elke zending.", terms=terms).passed
    assert run("Track all shipments.", "Volg alle Zendingen.", terms=terms).passed
    missing = run("Track every shipment.", "Volg elk pakket.", terms=terms)
    assert rules_hit(missing) == ["term"]
    assert missing.findings[0].side == "source"
    # No shipment in the source: nothing is required of the target.
    assert run("Track every order.", "Volg elke bestelling.", terms=terms).passed
    # A listed form only: the compound is reported (a false alarm, never a false pass).
    assert not run("Track every shipment.", "Volg elk zendingnummer.", terms=terms).passed


def test_arabic_terms_match_with_attached_particles_and_diacritics() -> None:
    terms = [{"source": ["shipment"], "target": ["شحنة"]}]
    for target in ("تابع الشحنة.", "تابع كل شُحنة.", "للشحنة رقم.", "وبالشحنة.", "تابع شحنتك."):
        assert run("Track the shipment.", target, market="ar", terms=terms).passed, target
    # Another word for the same thing is still a missing term.
    assert not run("Track the shipment.", "تابع الطرد.", market="ar", terms=terms).passed


def test_arabic_terms_ignore_the_article_inside_a_phrase() -> None:
    terms = [{"source": ["carrier"], "target": ["شركة النقل"]}]
    for target in ("أضف شركة نقل جديدة.", "اتصل بشركة النقل.", "شركة نقلك في الطريق."):
        assert run("Add a carrier.", target, market="ar", terms=terms).passed, target
    assert not run("Add a carrier.", "أضف الناقل.", market="ar", terms=terms).passed
    # The article is not ignored for forbidden phrases: "the cheapest" is not "cheaper".
    assert run("A fair price.", "سعر أرخص.", market="ar", forbidden=["الأرخص"]).passed


def test_forbidden_phrases_and_required_lines() -> None:
    report = run(
        "Fast delivery.",
        "Snelle levering met gratis\nverzending.",
        forbidden=["gratis verzending"],
        required_lines=["Prijzen zijn exclusief btw."],
    )
    assert rules_hit(report) == ["forbidden", "required-line"]
    forbidden = report.findings[0]
    assert (forbidden.line, forbidden.column) == (1, 21)
    assert report.findings[1].line == 0
    assert run(
        "Fast delivery.",
        "Snelle levering.\n\nPrijzen  zijn exclusief\nBTW.",
        required_lines=["Prijzen zijn exclusief btw."],
    ).passed


def test_arabic_required_line_ignores_diacritics_and_alef_forms() -> None:
    line = "الأسعار لا تشمل ضريبة القيمة المضافة."
    target = "توصيل سريع.\n\nالاسعار لا تشملُ ضريبة القيمة المضافة."
    assert run("Fast delivery.", target, market="ar", required_lines=[line]).passed


def test_dutch_form_of_address() -> None:
    informal = run("Open your portal.", "Open uw portaal, dan ziet u alles.", address="informal")
    assert rules_hit(informal) == ["address", "address"]
    assert run("Open your portal.", "Open je portaal a.u.b.", address="informal").passed
    formal = run("Open your portal.", "Open je portaal.", address="formal")
    assert rules_hit(formal) == ["address"]
    assert run("Open your portal.", "Open uw portaal.", address="formal").passed
    assert run("Open your portal.", "Open uw portaal.").passed  # no rule set


# --- brand file ----------------------------------------------------------------------------


def test_brand_file_is_strict() -> None:
    with pytest.raises(BrandError, match="adress"):
        parse_brand(raw_brand(adress="informal"))
    with pytest.raises(BrandError, match="not supported"):
        parse_brand({"brand": "X", "markets": {"de-DE": {}}})
    with pytest.raises(BrandError, match="Dutch-only"):
        parse_brand({"brand": "X", "markets": {"ar": {"address": "formal"}}})
    with pytest.raises(BrandError, match="empty"):
        parse_brand(raw_brand(forbidden=[" "]))
    with pytest.raises(BrandError, match="mapping"):
        parse_brand([])


def test_duplicate_keys_and_unknown_markets_are_rejected(tmp_path: Path, brand: Brand) -> None:
    path = tmp_path / "brand.yaml"
    path.write_text("brand: X\nmarkets:\n  nl-NL: {}\nmarkets:\n  ar: {}\n", encoding="utf-8")
    with pytest.raises(BrandError, match="duplicate key"):
        load_brand(path)
    with pytest.raises(BrandError, match="cannot read"):
        load_brand(tmp_path / "missing.yaml")
    with pytest.raises(BrandError, match="markets: ar, nl-NL"):
        PairChecker(brand, "fr-FR")


# --- facts, size, CLI, MCP -----------------------------------------------------------------


def test_with_facts_the_source_is_checked_first(example_facts: Facts, brand: Brand) -> None:
    checker = PairChecker(brand, "nl-NL", example_facts)
    report = checker.check("Led a team of 15 engineers.", "Leidde een team van 15 engineers.")
    assert "source" in rules_hit(report)
    assert report.source_report is not None
    assert not report.source_report.passed
    assert "source against the facts" in report.render()


def test_size_cap(brand: Brand) -> None:
    with pytest.raises(DocumentTooLarge, match="the target"):
        PairChecker(brand, "nl-NL").check("x", "x" * (MAX_DOCUMENT_CHARS + 1))


def test_cli_examples(capsys: pytest.CaptureFixture[str]) -> None:
    base = ["--source", SOURCE, "--brand", BRAND, "--market"]
    assert main(["check-pair", str(PAIR / "pass.nl.md"), *base, "nl-NL"]) == 0
    assert main(["check-pair", str(PAIR / "pass.ar.md"), *base, "ar"]) == 0
    capsys.readouterr()
    assert main(["check-pair", str(PAIR / "fail.nl.md"), *base, "nl-NL", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert sorted({f["rule"] for f in data["findings"]}) == [
        "address",
        "forbidden",
        "format",
        "name",
        "number",
        "required-line",
        "term",
    ]
    assert main(["brand", BRAND]) == 0
    assert "nl-NL: 2 term(s)" in capsys.readouterr().out


def test_cli_bad_input_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = ["--source", SOURCE, "--brand", BRAND, "--market"]
    assert main(["check-pair", str(PAIR / "pass.nl.md"), *base, "fr-FR"]) == 2
    assert main(["check-pair", str(tmp_path / "missing.md"), *base, "nl-NL"]) == 2
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe")
    assert main(["check-pair", str(bad), *base, "nl-NL"]) == 2
    assert "error:" in capsys.readouterr().err


def test_strict_makes_a_format_warning_fail(tmp_path: Path) -> None:
    source = tmp_path / "s.md"
    target = tmp_path / "t.md"
    brand_file = tmp_path / "b.yaml"
    source.write_text("Growth of 1.5 times.", encoding="utf-8")
    target.write_text("Een groei van 1.5 keer.", encoding="utf-8")
    brand_file.write_text("brand: X\nmarkets:\n  nl-NL: {}\n", encoding="utf-8")
    args = ["check-pair", str(target), "--source", str(source), "--brand", str(brand_file)]
    assert main([*args, "--market", "nl-NL"]) == 0
    assert main([*args, "--market", "nl-NL", "--strict"]) == 1


def test_mcp_tool(example_facts: Facts, brand: Brand) -> None:
    async def go() -> None:
        async with Client(build_server(example_facts, brand)) as client:
            names = sorted(t.name for t in (await client.list_tools()).tools)
            assert names == ["check_document", "check_localised", "list_facts"]
            res = await client.call_tool(
                "check_localised",
                {
                    "source_text": "We moved 1,200 shipments.",
                    "target_text": "We verwerkten 1,200 zendingen.",
                    "market": "nl-NL",
                },
            )
            assert res.structured_content is not None
            assert res.structured_content["passed"] is False
            assert "number" in {f["rule"] for f in res.structured_content["findings"]}
            unknown = await client.call_tool(
                "check_localised", {"source_text": "a", "target_text": "b", "market": "fr-FR"}
            )
            assert unknown.is_error
            listed = await client.call_tool("list_facts", {})
            assert listed.structured_content is not None
            assert "nl-NL" in listed.structured_content["brand"]["markets"]

    anyio.run(go)


def test_without_a_brand_file_the_server_is_as_in_v01(example_facts: Facts) -> None:
    async def go() -> None:
        async with Client(build_server(example_facts)) as client:
            names = sorted(t.name for t in (await client.list_tools()).tools)
            assert names == ["check_document", "list_facts"]

    anyio.run(go)


# --- found by an independent review ------------------------------------------------------


def test_arabic_forbidden_phrase_in_its_everyday_forms() -> None:
    for target in ("استمتع بالشحن المجاني.", "نقدم شحنًا مجانيًا.", "شحن مجانى للجميع."):
        report = run("Fast delivery.", target, market="ar", forbidden=["شحن مجاني"])
        assert rules_hit(report) == ["forbidden"], target


def test_a_forbidden_phrase_cannot_hide_behind_markup_or_invisible_characters() -> None:
    for target in (
        "Met gratis **verzending**.",
        "Met gratis-verzending.",
        "Met gra­tis verzending.",
        "Met gratis​ verzending.",
    ):
        report = run("Fast delivery.", target, forbidden=["gratis verzending"])
        assert rules_hit(report) == ["forbidden"], target


def test_a_changed_currency_is_reported_when_the_new_one_is_recognised() -> None:
    for target in ("Het kost € 49.", "Het kost 49 €.", "Het kost 49 Zwitserse frank."):
        ok = run("It costs $49.", target).passed
        assert ok is ("Zwitserse" in target), target  # an unknown wording reads as a plain 49
    for target in ("يكلف 49 دولارًا.", "يكلف 49$.", "يكلف 49 ريالًا."):
        assert not run("It costs €49.", target, market="ar").passed, target
    assert run("It costs $5,000.", "يكلف 5,000$.", market="ar").passed


def test_arabic_scale_word_after_eleven_to_ninety_nine() -> None:
    assert not run("We serve 20 customers.", "نخدم 20 ألفًا من العملاء.", market="ar").passed
    assert run("We serve 20,000 customers.", "نخدم 20 ألفًا من العملاء.", market="ar").passed
    assert run(
        "We moved 200 parcels for 2,000 customers.", "نقلنا مئتي طرد لألفي عميل.", market="ar"
    ).passed


def test_number_like_tokens_must_be_the_same_on_both_sides() -> None:
    cases = [
        ("Open from 09:00 to 17:00.", "Open van 09:00 tot 21:30."),
        ("Support 24/7.", "Support 12/5."),
        ("Results for Q3.", "Resultaten voor Q1."),
        ("Runs on version 3.12.1.", "Draait op versie 2.0.0."),
    ]
    for source, target in cases:
        report = run(source, target)
        assert set(rules_hit(report)) == {"number"}, target
    assert run(
        "Open from 09:00 to 17:00, 24/7, for B2B in Q3.",
        "Open van 09:00 tot 17:00, 24/7, voor B2B in Q3.",
    ).passed


def test_an_arabic_number_written_against_the_article_is_read() -> None:
    assert run("Our 350 drivers.", "سائقونا الـ350.", market="ar").passed
    assert not run("Our drivers.", "سائقونا الـ900.", market="ar").passed


def test_source_terms_ending_in_y() -> None:
    terms = [{"source": "delivery", "target": ["levering", "leveringen"]}]
    assert not run(
        "All deliveries are insured.", "Alle bezorgingen zijn verzekerd.", terms=terms
    ).passed
    assert run("All deliveries are insured.", "Alle leveringen zijn verzekerd.", terms=terms).passed


def test_a_required_line_must_stand_on_its_own() -> None:
    line = "Prijzen zijn exclusief btw."
    for target in (
        "Snel.\n\nNiet alle prijzen zijn exclusief btw.",
        "Snel.\n\n<!-- Prijzen zijn exclusief btw. -->",
    ):
        assert rules_hit(run("Fast.", target, required_lines=[line])) == ["required-line"], target
    for target in (
        "Snel.\n\n**Prijzen zijn exclusief btw.**",
        "Snel.\n> Prijzen zijn exclusief btw.",
    ):
        assert run("Fast.", target, required_lines=[line]).passed, target


def test_a_name_inside_a_link_is_not_a_use_of_it() -> None:
    source = "TrackBoard is new."
    target = "[Volgbord](https://example.test/TrackBoard) is nieuw."
    assert rules_hit(run(source, target, names=["TrackBoard"])) == ["name"]


def test_formal_market_fails_on_jezelf_and_dutch_percent_is_a_percentage() -> None:
    assert rules_hit(run("Treat yourself.", "Verwen jezelf.", address="formal")) == ["address"]
    assert run("A 15% discount.", "15 percent korting.").passed
    assert not run("Within 15 days.", "Binnen 15 percent.").passed


def test_a_leading_percent_sign_belongs_to_one_number_only() -> None:
    report = run("Down 30% in 6 months.", "انخفض 30% 6 أشهر.", market="ar")
    assert report.passed


def test_an_arabic_term_that_starts_with_hamza_and_lam_keeps_its_letters() -> None:
    terms = [{"source": "dairy", "target": ["ألبان"]}]
    assert not run("Fresh dairy.", "بان طازج.", market="ar", terms=terms).passed
    assert run("Fresh dairy.", "ألبان طازجة.", market="ar", terms=terms).passed


def test_a_range_ending_in_a_scaled_zero_does_not_crash() -> None:
    for source, target in (("From 5-0 million.", "Van 5-0 miljoen."), ("3-0k", "من 5-0 مليون")):
        run(source, target, market="ar" if "من" in target else "nl-NL")


def test_many_unmatched_numbers_stay_fast() -> None:
    import time

    source = " ".join(str(n) for n in range(100_000, 108_000))
    target = " ".join(str(n) for n in range(200_000, 208_000))
    started = time.perf_counter()
    report = run(source, target)
    assert len(report.findings) == 16_000
    assert time.perf_counter() - started < 5
    started = time.perf_counter()
    run("x", "5 vijf " * 16_000)
    assert time.perf_counter() - started < 5


def test_brand_yaml_with_odd_shapes_is_a_brand_error(tmp_path: Path) -> None:
    for i, text in enumerate(("? [a]\n: b\n", "[" * 3000)):
        path = tmp_path / f"b{i}.yaml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(BrandError, match="not valid YAML"):
            load_brand(path)
