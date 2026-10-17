"""Chunking keeps every document whole, and keeps canaries intact."""

from __future__ import annotations

import random
import string

import pytest

from fde_lab.retrieval.chunking import MAX_CHARS, chunk_document, chunk_id, chunk_text


def normalise(text: str) -> str:
    return " ".join(text.split())


class TestChunkText:
    def test_empty_and_blank_text_make_no_chunks(self):
        assert chunk_text("") == []
        assert chunk_text("   \n\t ") == []

    def test_short_text_is_one_chunk_unchanged(self):
        assert chunk_text("Short note. Two sentences.") == ["Short note. Two sentences."]

    def test_sentences_are_packed_up_to_the_limit(self):
        text = "One two three. Four five six. Seven eight nine."
        assert chunk_text(text, max_chars=30) == [
            "One two three. Four five six.",
            "Seven eight nine.",
        ]

    def test_a_chunk_never_starts_or_ends_mid_sentence_when_sentences_fit(self):
        text = " ".join(f"Sentence number {n} ends here." for n in range(40))
        for chunk in chunk_text(text, max_chars=100):
            assert chunk.startswith("Sentence") and chunk.endswith("here.")

    def test_an_oversized_sentence_is_split_on_words(self):
        text = " ".join(["word"] * 100)
        chunks = chunk_text(text, max_chars=50)
        assert len(chunks) > 1
        assert all(len(c) <= 50 for c in chunks)
        assert normalise(" ".join(chunks)) == normalise(text)

    def test_a_single_word_longer_than_the_limit_is_kept_whole(self):
        assert chunk_text("x" * 500, max_chars=50) == ["x" * 500]

    def test_ordinals_start_at_one_and_ids_are_stable(self):
        doc = {"doc_id": "SYN-D-0001", "title": "T", "body": "A. " * 200}
        rows = chunk_document(doc, max_chars=40)
        assert [r["ordinal"] for r in rows] == list(range(1, len(rows) + 1))
        assert rows[0]["chunk_id"] == chunk_id("SYN-D-0001", 1) == "SYN-D-0001#1"
        assert {r["doc_id"] for r in rows} == {"SYN-D-0001"}

    @pytest.mark.parametrize("seed", range(25))
    def test_random_text_is_reassembled_exactly(self, seed):
        rng = random.Random(seed)
        words = [
            "".join(rng.choices(string.ascii_lowercase, k=rng.randint(1, 12)))
            for _ in range(rng.randint(1, 120))
        ]
        text = ""
        for word in words:
            text += word + rng.choice([" ", " ", " ", ". ", "! ", "? ", "  "])
        limit = rng.choice([20, 60, 120, 280])
        chunks = chunk_text(text, max_chars=limit)
        assert normalise(" ".join(chunks)) == normalise(text)
        assert all(chunk.strip() for chunk in chunks)


class TestOnTheDataset:
    def test_every_document_is_reassembled_exactly(self, dataset):
        for doc in dataset["documents"]:
            rebuilt = " ".join(c["text"] for c in chunk_document(doc))
            assert normalise(rebuilt) == normalise(doc["body"]), doc["doc_id"]

    def test_every_canary_lands_whole_inside_exactly_one_chunk(self, dataset):
        for doc in dataset["documents"]:
            if doc["canary"] is None:
                continue
            holders = [c for c in chunk_document(doc) if doc["canary"] in c["text"]]
            assert len(holders) == 1, doc["doc_id"]

    def test_no_chunk_is_larger_than_the_limit(self, dataset):
        for doc in dataset["documents"]:
            for chunk in chunk_document(doc):
                assert len(chunk["text"]) <= MAX_CHARS, chunk["chunk_id"]

    def test_chunk_ids_are_unique_across_the_corpus(self, dataset):
        ids = [c["chunk_id"] for d in dataset["documents"] for c in chunk_document(d)]
        assert len(ids) == len(set(ids)) == 190
