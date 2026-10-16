import subprocess
import sys
from pathlib import Path

from fde_lab.datagen import digest, generate_all

GOLDEN = (Path(__file__).parent / "golden_digest.txt").read_text().strip()


def test_golden_digest(dataset_dir):
    """The default dataset must not change unless the golden digest is updated on purpose."""
    assert digest(dataset_dir) == GOLDEN


def test_same_seed_same_digest(tmp_path):
    generate_all(7, tmp_path / "a", members=50, providers=6, requests=40)
    generate_all(7, tmp_path / "b", members=50, providers=6, requests=40)
    assert digest(tmp_path / "a") == digest(tmp_path / "b")


def test_different_seed_differs(tmp_path):
    generate_all(7, tmp_path / "a", members=50, providers=6, requests=40)
    generate_all(8, tmp_path / "b", members=50, providers=6, requests=40)
    assert digest(tmp_path / "a") != digest(tmp_path / "b")


def test_independent_of_python_hash_seed(tmp_path):
    """String-seeded streams must not depend on PYTHONHASHSEED."""
    digests = set()
    for hash_seed in ("1", "2", "random"):
        out = tmp_path / f"h{hash_seed}"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "fde_lab.datagen",
                "--seed",
                "7",
                "--out",
                str(out),
                "--members",
                "50",
                "--providers",
                "6",
                "--requests",
                "40",
            ],
            check=True,
            capture_output=True,
            env={"PYTHONHASHSEED": hash_seed, "PATH": ""},
        )
        digests.add(digest(out))
    assert len(digests) == 1


def test_streams_are_independent(tmp_path):
    """Generating more requests must not change members, providers or users."""
    generate_all(7, tmp_path / "small", members=50, providers=6, requests=40)
    generate_all(7, tmp_path / "large", members=50, providers=6, requests=400)
    for name in ("members.jsonl", "providers.jsonl", "users.json"):
        assert (tmp_path / "small" / name).read_bytes() == (tmp_path / "large" / name).read_bytes()
