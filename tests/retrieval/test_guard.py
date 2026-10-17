"""The second line of defence, and the assistant that depends on it. No database needed."""

from __future__ import annotations

import pytest

from fde_lab.auth.tokens import Identity
from fde_lab.retrieval.assistant import Assistant, extractive_model
from fde_lab.retrieval.guard import PermissionLeak, verify_passages
from fde_lab.retrieval.passage import Passage

REVIEWER_NORTH = Identity("s-1", "r@acme.test", "reviewer", "north", ())
ADMIN = Identity("s-2", "a@acme.test", "admin", "*", ())

POLICY = Passage(
    "P#1", "P", "policy", "Policy", "Prior authorization is required. Second sentence.",
    "*", ("reviewer", "medical_director", "claims_analyst", "admin"),
)  # fmt: skip
NORTH_NOTE = Passage(
    "N#1",
    "N",
    "clinical_note",
    "North note",
    "North only. CANARY-N",
    "north",
    ("reviewer", "medical_director"),
)
COAST_NOTE = Passage(
    "C#1",
    "C",
    "clinical_note",
    "Coast note",
    "Coast only. CANARY-C",
    "coast",
    ("reviewer", "medical_director"),
)
MEMO = Passage(
    "M#1", "M", "exception_memo", "Memo", "Directors only. CANARY-M", "*", ("medical_director",)
)


class FixedRetriever:
    def __init__(self, passages):
        self.passages = passages
        self.calls = []

    def search(self, user, question, k=5):
        self.calls.append((user, question, k))
        return list(self.passages)


class SpyModel:
    def __init__(self):
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return "model output"


class TestVerifyPassages:
    def test_readable_passages_pass_through_unchanged(self):
        assert verify_passages(REVIEWER_NORTH, [POLICY, NORTH_NOTE]) == [POLICY, NORTH_NOTE]

    @pytest.mark.parametrize("bad", [COAST_NOTE, MEMO])
    def test_an_unreadable_passage_raises(self, bad):
        with pytest.raises(PermissionLeak) as err:
            verify_passages(REVIEWER_NORTH, [POLICY, bad])
        assert err.value.chunk_ids == [bad.chunk_id]

    def test_the_error_names_ids_and_never_contains_the_text(self):
        with pytest.raises(PermissionLeak) as err:
            verify_passages(REVIEWER_NORTH, [COAST_NOTE, MEMO])
        message = str(err.value)
        assert "CANARY" not in message and "Coast only" not in message
        assert err.value.chunk_ids == ["C#1", "M#1"]

    def test_it_is_all_or_nothing_not_a_silent_drop(self):
        with pytest.raises(PermissionLeak):
            verify_passages(REVIEWER_NORTH, [POLICY, NORTH_NOTE, COAST_NOTE])

    def test_the_caller_matters(self):
        assert verify_passages(ADMIN, [POLICY]) == [POLICY]
        with pytest.raises(PermissionLeak):
            verify_passages(ADMIN, [NORTH_NOTE])


class TestAssistantFailsClosed:
    def test_a_misbehaving_retriever_never_reaches_the_model(self):
        model = SpyModel()
        assistant = Assistant(FixedRetriever([POLICY, COAST_NOTE]), model)
        with pytest.raises(PermissionLeak):
            assistant.ask(REVIEWER_NORTH, "anything")
        assert model.prompts == []

    def test_a_misbehaving_retriever_is_caught_by_search_too(self):
        with pytest.raises(PermissionLeak):
            Assistant(FixedRetriever([MEMO]), SpyModel()).search(REVIEWER_NORTH, "q")

    def test_the_model_sees_exactly_the_checked_passages(self):
        model = SpyModel()
        answer = Assistant(FixedRetriever([POLICY, NORTH_NOTE]), model).ask(REVIEWER_NORTH, "Why?")
        assert model.prompts == [answer.prompt]
        assert "CANARY-N" in answer.prompt and "Prior authorization is required" in answer.prompt
        assert [s.doc_id for s in answer.sources] == ["P", "N"]
        assert answer.text == "model output"

    def test_k_is_passed_to_the_retriever(self):
        retriever = FixedRetriever([POLICY])
        Assistant(retriever, SpyModel(), k=7).ask(REVIEWER_NORTH, "q")
        Assistant(retriever, SpyModel(), k=7).search(REVIEWER_NORTH, "q", k=2)
        assert [call[2] for call in retriever.calls] == [7, 2]

    def test_nothing_found_still_calls_the_model_with_an_explicit_empty_context(self):
        model = SpyModel()
        answer = Assistant(FixedRetriever([]), model).ask(REVIEWER_NORTH, "q")
        assert "(no sources available to this caller)" in model.prompts[0]
        assert answer.sources == ()


class TestExtractiveStandIn:
    def test_quotes_the_first_sentence_of_the_first_source_with_its_citation(self):
        answer = Assistant(FixedRetriever([POLICY]), extractive_model).ask(REVIEWER_NORTH, "q")
        assert answer.text == "Prior authorization is required. [S1]"

    def test_says_so_when_there_are_no_sources(self):
        answer = Assistant(FixedRetriever([]), extractive_model).ask(REVIEWER_NORTH, "q")
        assert "do not answer" in answer.text
