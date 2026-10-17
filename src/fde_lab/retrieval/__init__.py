"""Permission-filtered retrieval and prompt assembly.

The access filter runs inside the retrieval query (through Postgres row-level security), so text
the caller may not read is never fetched, ranked, or placed in a prompt. Install the database
extra with `pip install -e ".[db]"`. The pure parts (chunking, query building, prompt assembly)
import without it.
"""
