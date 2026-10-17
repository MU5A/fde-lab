"""Retrieve, check, build the prompt, call the model. The model is a plain function of a prompt.

Because the model sees only the prompt string, "what the model saw" is exactly the value that
tests can capture and inspect.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from .guard import verify_passages
from .passage import Passage
from .prompt import build_prompt

if TYPE_CHECKING:
    from ..auth.tokens import Identity

Model = Callable[[str], str]


class Retriever(Protocol):
    def search(self, user: Identity, question: str, k: int = 5) -> list[Passage]: ...


@dataclass(frozen=True)
class Source:
    doc_id: str
    chunk_id: str
    title: str


@dataclass(frozen=True)
class Answer:
    text: str
    sources: tuple[Source, ...]
    prompt: str  # kept for tests and audit. Never returned by the API.


class Assistant:
    def __init__(self, retriever: Retriever, model: Model, k: int = 5):
        self._retriever = retriever
        self._model = model
        self._k = k

    def search(self, user: Identity, question: str, k: int | None = None) -> list[Passage]:
        return verify_passages(user, self._retriever.search(user, question, k or self._k))

    def ask(self, user: Identity, question: str) -> Answer:
        passages = self.search(user, question)
        prompt = build_prompt(question, passages)
        return Answer(
            text=self._model(prompt),
            sources=tuple(Source(p.doc_id, p.chunk_id, p.title) for p in passages),
            prompt=prompt,
        )


_FIRST_SOURCE = re.compile(r"\[S1\][^\n]*\n(.+)")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def extractive_model(prompt: str) -> str:
    """A stand-in for the language model: quote the first sentence of the first source.

    It exists so the pipeline runs end to end with no model. Day 12 replaces it with a local
    quantized model.
    """
    match = _FIRST_SOURCE.search(prompt)
    if match is None:
        return "The sources available to you do not answer this question."
    return f"{_SENTENCE_END.split(match.group(1).strip())[0]} [S1]"
