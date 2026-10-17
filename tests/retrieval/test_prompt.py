"""What the model is shown."""

from __future__ import annotations

from fde_lab.retrieval.passage import Passage
from fde_lab.retrieval.prompt import INSTRUCTIONS, build_prompt


def passage(n: int, text: str = "Body text.") -> Passage:
    return Passage(
        chunk_id=f"SYN-D-000{n}#1",
        doc_id=f"SYN-D-000{n}",
        doc_type="policy",
        title=f"Title {n}",
        text=text,
        tenant="*",
        allowed_roles=("reviewer",),
        score=0.987654,
    )


def test_sources_are_numbered_titled_and_in_rank_order():
    prompt = build_prompt("What now?", [passage(1, "First."), passage(2, "Second.")])
    assert prompt.index("[S1] Title 1 (SYN-D-0001)\nFirst.") < prompt.index(
        "[S2] Title 2 (SYN-D-0002)\nSecond."
    )


def test_the_question_and_instructions_are_present():
    prompt = build_prompt("  What now?  ", [passage(1)])
    assert INSTRUCTIONS in prompt
    assert prompt.rstrip().endswith("Question: What now?")


def test_access_metadata_and_scores_are_not_shown_to_the_model():
    prompt = build_prompt("q", [passage(1)])
    assert "0.9876" not in prompt
    assert "allowed_roles" not in prompt
    assert "reviewer" not in prompt.split("Sources:")[1]


def test_no_sources_says_so_explicitly():
    prompt = build_prompt("q", [])
    assert "(no sources available to this caller)" in prompt
    assert "[S1]" not in prompt.split("Sources:")[1]
