"""The evaluation code produces the published numbers, so it is tested like everything else."""

from __future__ import annotations

from fde_lab.datagen.acl import can_read
from fde_lab.datagen.generate import make_users
from fde_lab.datagen.reference import PROCEDURES
from fde_lab.retrieval.evaluate import (
    PARAPHRASES,
    Case,
    hit_rates,
    note_cases,
    pessimistic_rank,
    policy_cases,
    readable_cases,
)
from fde_lab.retrieval.passage import Passage


def p(doc_id: str, score: float, n: int = 1) -> Passage:
    return Passage(f"{doc_id}#{n}", doc_id, "policy", "T", "text", "*", ("reviewer",), score)


class TestPessimisticRank:
    def test_a_clear_winner_is_rank_one(self):
        assert pessimistic_rank("A", [p("A", 3.0), p("B", 2.0), p("C", 1.0)]) == 1

    def test_the_rank_follows_the_documents_ahead_of_it(self):
        assert pessimistic_rank("C", [p("A", 3.0), p("B", 2.0), p("C", 1.0)]) == 3

    def test_a_tie_with_another_document_counts_against_it(self):
        assert pessimistic_rank("A", [p("A", 1.0), p("B", 1.0)]) == 2
        assert pessimistic_rank("B", [p("A", 1.0), p("B", 1.0)]) == 2

    def test_a_large_tie_puts_it_last_in_the_group(self):
        passages = [p(d, 0.1) for d in "ABCDEF"]
        assert pessimistic_rank("A", passages) == 6

    def test_a_lower_score_does_not_count_against_it(self):
        assert pessimistic_rank("A", [p("A", 1.0), p("B", 0.9)]) == 1

    def test_other_chunks_of_the_same_document_never_count_against_it(self):
        assert pessimistic_rank("A", [p("A", 3.0, 1), p("A", 3.0, 2), p("B", 1.0)]) == 1

    def test_it_uses_the_best_chunk_of_the_expected_document(self):
        passages = [p("B", 2.0), p("A", 3.0, 1), p("A", 1.0, 2)]
        assert pessimistic_rank("A", passages) == 1

    def test_a_document_that_was_not_returned_has_no_rank(self):
        assert pessimistic_rank("Z", [p("A", 1.0)]) is None
        assert pessimistic_rank("Z", []) is None

    def test_several_chunks_of_one_competitor_count_once(self):
        assert pessimistic_rank("A", [p("B", 2.0, 1), p("B", 2.0, 2), p("A", 1.0)]) == 2


class TestHitRates:
    def run(self, results_by_question, cases, ks=(1, 3, 5)):
        return hit_rates(lambda q, k: results_by_question[q], cases, ks)

    def test_fractions_per_kind_and_cutoff(self):
        cases = [Case("x", "q1", "A"), Case("x", "q2", "A"), Case("y", "q3", "A")]
        results = {
            "q1": [p("A", 3.0), p("B", 1.0)],  # rank 1
            "q2": [p("B", 3.0), p("C", 2.0), p("A", 1.0)],  # rank 3
            "q3": [p("B", 3.0)],  # not returned
        }
        rates = self.run(results, cases)
        assert rates["x"] == {1: 0.5, 3: 1.0, 5: 1.0}
        assert rates["y"] == {1: 0.0, 3: 0.0, 5: 0.0}

    def test_a_tie_cannot_turn_into_a_hit_at_rank_one(self):
        rates = self.run({"q": [p("A", 0.1), p("B", 0.1)]}, [Case("x", "q", "A")])
        assert rates["x"][1] == 0.0 and rates["x"][3] == 1.0

    def test_the_search_is_asked_for_enough_depth_to_see_ties(self):
        asked = []
        hit_rates(lambda q, k: asked.append(k) or [], [Case("x", "q", "A")])
        assert asked == [20]


class TestQuestionSets:
    def test_every_procedure_gets_four_policy_questions_pointing_at_its_own_policy(self, dataset):
        cases = policy_cases(dataset["documents"])
        assert len(cases) == 4 * len(PROCEDURES)
        titles = {d["doc_id"]: d["title"] for d in dataset["documents"]}
        for case in cases:
            assert titles[case.expected_doc_id].startswith("Utilization criteria: ")
        assert {c.kind for c in cases} == {
            "policy_question",
            "policy_keywords",
            "policy_code",
            "policy_paraphrase",
        }

    def test_the_paraphrases_do_not_contain_the_procedure_name(self):
        for procedure in PROCEDURES:
            assert procedure.name.lower() not in PARAPHRASES[procedure.code].lower()

    def test_one_note_question_per_clinical_note(self, dataset):
        cases = note_cases(dataset["documents"])
        assert len(cases) == 60
        by_id = {d["doc_id"]: d for d in dataset["documents"]}
        for case in cases:
            assert by_id[case.expected_doc_id]["ref_request_id"] in case.question

    def test_readable_cases_keeps_only_questions_the_user_could_have_answered(self, dataset):
        docs = dataset["documents"]
        everything = policy_cases(docs) + note_cases(docs)
        by_id = {d["doc_id"]: d for d in docs}
        for user in make_users(42):
            kept = readable_cases(user, docs, everything)
            assert all(can_read(user, by_id[c.expected_doc_id]) for c in kept)
        analyst = next(u for u in make_users(42) if u["role"] == "claims_analyst")
        assert {c.kind for c in readable_cases(analyst, docs, everything)} <= {
            "policy_question",
            "policy_keywords",
            "policy_code",
            "policy_paraphrase",
        }
