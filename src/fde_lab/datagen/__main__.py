"""Command line entry point: python -m fde_lab.datagen --seed 42 --out data/generated"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from .generate import FILES, digest, generate_all


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic Acme Health Plan dataset.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--members", type=int, default=2000)
    parser.add_argument("--providers", type=int, default=60)
    parser.add_argument("--requests", type=int, default=1500)
    parser.add_argument("--print-digest", action="store_true")
    args = parser.parse_args()

    data = generate_all(args.seed, args.out, args.members, args.providers, args.requests)

    print(f"wrote {len(FILES)} files to {args.out}")
    for key in ("users", "providers", "members", "requests", "documents"):
        print(f"  {key:<10} {len(data[key]):>6}")
    routes = Counter(t["route"] for t in data["truth"])
    total = sum(routes.values())
    print("route distribution:")
    for name, count in sorted(routes.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<20} {count:>5}  {100 * count / total:5.1f}%")
    if args.print_digest:
        print(f"digest: {digest(args.out)}")


if __name__ == "__main__":
    main()
