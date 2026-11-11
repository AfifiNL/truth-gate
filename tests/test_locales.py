"""Number reading for Dutch and Arabic targets, and Arabic folding."""

from __future__ import annotations

from decimal import Decimal

import pytest

from truth_gate.locales import fold, language_of, load, scan_target
from truth_gate.numbers import scan


def labels(text: str, locale: str) -> list[str]:
    return [q.label() for q in scan(text, locale)[0]]


def test_english_is_the_default_and_unchanged() -> None:
    assert labels("1,200 users and 1.5 million", "en") == ["1200", "1500000"]
    assert scan("1,200 users") == scan("1,200 users", "en")


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("1.200 klanten", ["1200"]),
        ("1,200 klanten", ["1.2"]),  # the source's "1,200" copied into Dutch reads as 1.2
        ("3,5% groei", ["3.5%"]),
        ("€ 1.200.000,50", ["EUR 1200000.5"]),
        ("1,2 mln euro", ["EUR 1200000"]),
        ("5 miljoen dollar", ["USD 5000000"]),
        ("12 procent", ["12%"]),
        ("1 200 klanten", ["1200"]),
        ("de 2e editie, de 20ste keer", ["2", "20"]),
        ("40GB en 10–15%", ["40gb", "10%", "15%"]),
        ("in 2021.", ["2021"]),
    ],
)
def test_dutch_digits(text: str, want: list[str]) -> None:
    assert labels(text, "nl") == want


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("twaalf maanden", ["12"]),
        ("vijfentwintig mensen", ["25"]),
        ("tweeëntwintig mensen", ["22"]),
        ("tweeduizend orders", ["2000"]),
        ("drie honderd orders", ["300"]),
        ("duizend klanten", ["1000"]),
        ("een miljoen bezoekers", ["1000000"]),
        ("een klant, één klant", []),  # the article, and "one" without a scale word
    ],
)
def test_dutch_number_words(text: str, want: list[str]) -> None:
    assert labels(text, "nl") == want


def test_dutch_skips_and_english_format() -> None:
    found = scan_target("versie 3.12.1, 24/7, 10:30, 1,2,3 en 1.5 keer", "nl")
    assert [q.label() for q in found.quantities] == ["1.5"]
    assert [q.text for q in found.english_format] == ["1.5"]
    assert sorted(s.rule for s in found.skipped) == ["comma", "slash", "time", "version"]


def test_dutch_thousands_are_not_english_format() -> None:
    found = scan_target("1.200 en 1.200.000", "nl")
    assert [q.value for q in found.quantities] == [Decimal(1200), Decimal(1200000)]
    assert found.english_format == []


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("لدينا ١٬٢٠٠ عميل", ["1200"]),
        ("نمو ٣٫٥٪", ["3.5%"]),
        ("بنسبة %20 خلال 3 سنوات", ["20%", "3"]),  # the sign typed first
        ("15 بالمئة و10 في المائة", ["15%", "10%"]),
        ("ب20 دولار", ["USD 20"]),  # an attached preposition is not a name like "B2B"
        ("5 ملايين يورو", ["EUR 5000000"]),
        ("1,200 عميل و1.5 مليون", ["1200", "1500000"]),
        ("۱۲ شهرا", ["12"]),  # Persian digits
    ],
)
def test_arabic_digits(text: str, want: list[str]) -> None:
    assert labels(text, "ar") == want


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("خمسة آلاف عميل", ["5000"]),
        ("وألف طلب ومليون زيارة", ["1000", "1000000"]),
        ("آلاف العملاء", []),  # "thousands of customers" is not a number
        ("ست سنوات", ["6"]),
        ("لست متأكدا", []),  # "I am not sure", not "for six"
        ("وست سنوات", ["6"]),
        ("بثلاث لغات", ["3"]),
        ("واحد من الأسباب", []),
        ("واحد مليون", ["1000000"]),
        ("مئتان وألفين", ["200", "2000"]),
        ("الثلاثاء", []),  # Tuesday contains the letters of "three"
        ("اثني عشر شخصا", ["12"]),
        ("ثلاث عشرة شحنة", ["13"]),
        ("عشرين عميلا", ["20"]),
        ("خمسة وعشرين شخصا", ["25"]),
        ("خلال ساعتين", ["2"]),  # a listed dual noun: two hours
        ("لشهرين", ["2"]),
        ("مستودعان", []),  # a dual that is not listed is not read
        ("من الاثنين إلى السبت", []),  # Monday to Saturday: Monday is not "the two"
        ("من الإثنين إلى الجمعة", []),
        ("اثنين من العملاء واثنان آخران", ["2", "2"]),
    ],
)
def test_arabic_number_words(text: str, want: list[str]) -> None:
    assert labels(text, "ar") == want


def test_arabic_offsets_point_at_the_original_text() -> None:
    text = "‏TrackBoard‏ سعره ١٬٢٠٠ دولار"
    (q,) = scan(text, "ar")[0]
    assert text[q.start : q.end] == q.text == "١٬٢٠٠ دولار"


def test_fold_removes_marks_and_keeps_an_index() -> None:
    text = "أَهلاً بـ‏TrackBoard"
    folded, index = fold(text, "ar")
    assert folded == "اهلا بTrackBoard"
    assert index is not None
    assert [text[i] for i in index][:3] == ["أ", "ه", "ل"]
    assert fold("één", "nl") == ("één", None)


def test_data_files_load_and_fold_their_forms() -> None:
    ar = load("ar")
    assert ar.scale_words["الف"] == 1000  # written "ألف" in the data file
    assert "ست" in ar.no_particle
    nl = load("nl")
    assert nl.number_words["twaalf"] == 12
    with pytest.raises(ValueError, match="unsupported"):
        load("de")
    assert language_of("nl-NL") == "nl"
