"""Measure retrieval quality on synthetic questions, per kind of question.

Run against the compose database:  python -m fde_lab.retrieval.evaluate

A hit means the expected document ranks within the top k documents, with ties counted against
retrieval. The numbers describe
this synthetic corpus only. The questions share vocabulary with the documents, so they say how
well keyword search works when wording overlaps, and nothing about paraphrased real questions.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..datagen.acl import can_read
from ..datagen.reference import PROCEDURES
from .passage import Passage

KS = (1, 3, 5)


@dataclass(frozen=True)
class Case:
    kind: str
    question: str
    expected_doc_id: str


# Everyday wording for each procedure, written once and not tuned afterwards. None of these
# reuses the procedure's name, so they measure what keyword search does when wording differs.
PARAPHRASES = {
    "PX-1001": "a scan of the lower back",
    "PX-1002": "imaging of the knee joint",
    "PX-1003": "an artificial knee joint operation",
    "PX-1004": "joining vertebrae together in the lower back",
    "PX-1005": "an overnight breathing test at a sleep clinic",
    "PX-1006": "twelve rehab visits",
    "PX-1007": "an eye lens operation",
    "PX-1008": "a heart exercise test",
    "PX-1009": "arthritis drip treatment",
    "PX-1010": "inherited cancer gene testing",
}


def policy_cases(documents: Sequence[dict]) -> list[Case]:
    by_title = {d["title"]: d["doc_id"] for d in documents if d["doc_type"] == "policy"}
    cases = []
    for procedure in PROCEDURES:
        doc_id = by_title[f"Utilization criteria: {procedure.name}"]
        cases += [
            Case(
                "policy_question",
                f"What are the prior authorization criteria for {procedure.name}?",
                doc_id,
            ),
            Case("policy_keywords", procedure.name, doc_id),
            Case("policy_code", procedure.code, doc_id),
            Case(
                "policy_paraphrase",
                f"What does the plan require before approving {PARAPHRASES[procedure.code]}?",
                doc_id,
            ),
        ]
    return cases


def note_cases(documents: Sequence[dict]) -> list[Case]:
    return [
        Case("note_by_request", f"clinical note for {d['ref_request_id']}", d["doc_id"])
        for d in documents
        if d["doc_type"] == "clinical_note"
    ]


DEPTH = 20


def pessimistic_rank(expected_doc_id: str, passages: Sequence[Passage]) -> int | None:
    """Rank of the expected document among documents, with every tie counted against it.

    Other documents whose best chunk scores the same as the expected one might be ordered either
    way, so all of them are assumed to come first. Chunks of the expected document itself do not
    count against it. Without tie handling a document can look found only because a tie happened
    to be broken in its favour (see docs/retrieval.md). None means it was not returned at all.
    """
    best = max((p.score for p in passages if p.doc_id == expected_doc_id), default=None)
    if best is None:
        return None
    ahead = {p.doc_id for p in passages if p.doc_id != expected_doc_id and p.score >= best}
    return 1 + len(ahead)


def hit_rates(
    search: Callable[[str, int], list[Passage]], cases: Sequence[Case], ks: Sequence[int] = KS
) -> dict[str, dict[int, float]]:
    """Fraction of cases per kind whose expected document is within the top k documents.

    Ties are counted against retrieval, and `DEPTH` chunks are fetched so large ties are visible.
    """
    hits: dict[str, dict[int, int]] = {}
    totals: dict[str, int] = {}
    for case in cases:
        rank = pessimistic_rank(case.expected_doc_id, search(case.question, DEPTH))
        totals[case.kind] = totals.get(case.kind, 0) + 1
        row = hits.setdefault(case.kind, dict.fromkeys(ks, 0))
        for k in ks:
            row[k] += rank is not None and rank <= k
    return {kind: {k: row[k] / totals[kind] for k in ks} for kind, row in hits.items()}


def _format(label: str, rates: dict[str, dict[int, float]]) -> str:
    lines = [f"{label}"]
    for kind, row in rates.items():
        cells = "  ".join(f"hit@{k} {value:5.1%}" for k, value in row.items())
        lines.append(f"  {kind:16} {cells}")
    return "\n".join(lines)


def readable_cases(user: dict, documents: Sequence[dict], cases: Sequence[Case]) -> list[Case]:
    """Only questions whose answer this user may read, so a miss is a retrieval miss."""
    by_id = {d["doc_id"]: d for d in documents}
    return [c for c in cases if can_read(user, by_id[c.expected_doc_id])]


def main() -> None:
    import tempfile
    from pathlib import Path

    from ..auth.tokens import Identity
    from ..datagen import generate_all
    from ..datagen.generate import make_users
    from ..db.session import make_pool
    from .pg import PgRetriever

    dsn = os.environ.get("DATABASE_URL", "postgresql://fde_app:synthetic-app@localhost:5432/fdelab")
    with tempfile.TemporaryDirectory() as tmp:
        documents = generate_all(42, Path(tmp))["documents"]
    cases = policy_cases(documents) + note_cases(documents)
    users = make_users(42)
    pool = make_pool(dsn)
    retriever = PgRetriever(pool)
    for label, role, region in (
        ("reviewer (north)", "reviewer", "north"),
        ("medical director", "medical_director", "*"),
        ("claims analyst (north)", "claims_analyst", "north"),
        ("admin", "admin", "*"),
    ):
        user = next(u for u in users if u["role"] == role and u["region"] == region)
        identity = Identity(user["user_id"], user["username"], role, region, ())
        mine = readable_cases(user, documents, cases)
        rates = hit_rates(lambda q, k, who=identity: retriever.search(who, q, k), mine)
        print(_format(f"{label}, {len(mine)} questions", rates))
    pool.close()


if __name__ == "__main__":
    main()
