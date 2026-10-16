import json
from pathlib import Path

import pytest

from fde_lab.datagen import generate_all

SEED = 42


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture(scope="session")
def dataset_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("acme")
    generate_all(SEED, out)
    return out


@pytest.fixture(scope="session")
def dataset(dataset_dir) -> dict:
    return {
        "users": json.loads((dataset_dir / "users.json").read_text()),
        "members": read_jsonl(dataset_dir / "members.jsonl"),
        "providers": read_jsonl(dataset_dir / "providers.jsonl"),
        "requests": read_jsonl(dataset_dir / "preauth_requests.jsonl"),
        "truth": read_jsonl(dataset_dir / "ground_truth.jsonl"),
        "documents": read_jsonl(dataset_dir / "documents.jsonl"),
    }
