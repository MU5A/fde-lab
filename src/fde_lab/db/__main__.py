"""Create the schema and load the dataset: `python -m fde_lab.db`.

Environment:
  DATABASE_ADMIN_URL  a superuser connection (default: the local compose database)
"""

from __future__ import annotations

import argparse
import os

from .migrate import rebuild

DEFAULT_ADMIN_URL = "postgresql://postgres:postgres@localhost:5432/fdelab"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the fde schema and load the dataset.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--admin-dsn", default=os.environ.get("DATABASE_ADMIN_URL", DEFAULT_ADMIN_URL)
    )
    args = parser.parse_args()
    data = rebuild(args.admin_dsn, args.seed)
    print({name: len(rows) for name, rows in data.items() if name != "truth"})


if __name__ == "__main__":
    main()
