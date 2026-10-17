"""The question is split into plain words. Nothing here can become query syntax."""

from __future__ import annotations

import pytest

from fde_lab.retrieval.query import MAX_WORD_LENGTH, MAX_WORDS, words


def test_words_are_lowercased_deduplicated_and_keep_their_order():
    assert words("Lumbar spine MRI lumbar SPINE") == ["lumbar", "spine", "mri"]


def test_codes_stay_in_one_piece_so_postgres_parses_them_like_the_index_did():
    assert words("PX-1001 requirements") == ["px-1001", "requirements"]
    assert "syn-r-000375" in words("clinical note for SYN-R-000375")


def test_blank_input_has_no_words():
    assert words("") == []
    assert words("   \t\n ") == []


def test_control_characters_are_removed_including_nul():
    assert words("lumbar\x00spine") == ["lumbarspine"]
    assert words("\x00 \x01") == []


def test_the_number_of_words_is_capped():
    assert len(words(" ".join(f"w{n}" for n in range(500)))) == MAX_WORDS


def test_a_very_long_word_is_dropped_not_truncated():
    assert words("ok " + "x" * (MAX_WORD_LENGTH + 1)) == ["ok"]


@pytest.mark.parametrize(
    "text",
    [
        "a & b",
        "a | b",
        "!a",
        "a:*",
        "a <-> b",
        "(a)",
        "'a'",
        "a\\b",
        "a' OR '1'='1",
        "; DROP TABLE x",
    ],
)
def test_operator_characters_pass_through_as_text_for_postgres_to_treat_as_text(text):
    # They are not interpreted here and not interpolated into SQL later. The database tests send
    # every one of these through a real search to prove they cannot break or steer the query.
    assert all(isinstance(w, str) and w for w in words(text))
