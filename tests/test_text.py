from __future__ import annotations

import time

import pytest

from truth_gate.text import content_words, line_col, mask, sentence_spans, stem


def test_mask_keeps_offsets_and_hides_code_comments_urls_and_list_markers() -> None:
    doc = (
        "1. Led `12` people, see https://example.com/a/2019 and [x](https://e.x/7).\n"
        "```\n99\n```\n~~~\n98\n~~~\n<!-- 97 -->"
    )
    masked = mask(doc)
    assert len(masked) == len(doc)
    assert masked.count("\n") == doc.count("\n")
    for hidden in ("1.", "12", "2019", "/7", "99", "98", "97"):
        assert hidden not in masked
    assert "Led" in masked
    assert "people" in masked


def test_list_markers_follow_markdown_rules() -> None:
    doc = "Intro line\n1. first\n2. second\n\nA sentence that wraps onto a line starting\n40. Next"
    masked = mask(doc)
    assert "1." not in masked
    assert "2." not in masked  # inside the list started by "1."
    assert "40." in masked  # a wrapped sentence, not a list: its number is checked


def test_unclosed_fences_and_comments_stay_unmasked() -> None:
    assert "99" in mask("```\n99\n")
    assert "99" in mask("<!-- 99")


@pytest.mark.parametrize(
    "adversarial",
    ["<!--" * 50_000, "](" * 100_000, "```\n" * 50_000, "````\n```\n" * 25_000, "`a" * 100_000],
)
def test_masking_is_linear_on_adversarial_input(adversarial: str) -> None:
    started = time.perf_counter()
    mask(adversarial)
    # Linear work takes well under 0.5 s here; the old quadratic patterns took over 20 s.
    assert time.perf_counter() - started < 3.0


def test_stem_makes_common_forms_equal() -> None:
    pairs = [
        ("conferences", "conference"),
        ("migrated", "migration"),
        ("engineers", "engineering"),
        ("cities", "city"),
        ("costs", "cost"),
    ]
    for a, b in pairs:
        assert stem(a) == stem(b), (a, b)


def test_content_words_drop_stopwords_units_and_short_words() -> None:
    assert content_words("Led a team of 12 engineers for 5 years") == {"led", "team", "engineer"}


def test_every_line_break_ends_a_sentence() -> None:
    text = "One 1.5 two. Three\n- four\n\nfive\nsix"
    parts = [text[s.start : s.end].strip() for s in sentence_spans(text)]
    assert parts == ["One 1.5 two.", "Three", "- four", "five", "six"]


def test_line_col_is_one_based() -> None:
    assert line_col("ab\ncd", 3) == (2, 1)
    assert line_col("ab\ncd", 0) == (1, 1)
