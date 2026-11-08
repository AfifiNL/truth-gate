from __future__ import annotations

from truth_gate.text import content_words, line_col, mask, sentence_spans, stem


def test_mask_keeps_offsets_and_hides_code_urls_and_list_markers() -> None:
    doc = "1. Led `12` people, see https://example.com/a/2019 and [x](https://e.x/7).\n```\n99\n```"
    masked = mask(doc)
    assert len(masked) == len(doc)
    assert masked.count("\n") == doc.count("\n")
    for hidden in ("12", "2019", "99", "/7"):
        assert hidden not in masked
    assert "Led" in masked
    assert "people" in masked


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


def test_sentences_split_on_full_stops_bullets_and_paragraphs() -> None:
    text = "One 1.5 two. Three\n- four\n\nfive"
    parts = [text[s.start : s.end].strip() for s in sentence_spans(text)]
    assert parts == ["One 1.5 two.", "Three", "- four", "five"]


def test_line_col_is_one_based() -> None:
    assert line_col("ab\ncd", 3) == (2, 1)
    assert line_col("ab\ncd", 0) == (1, 1)
