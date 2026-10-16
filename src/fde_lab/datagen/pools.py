"""Name pools for the synthetic Acme Health Plan dataset.

Everything here is fictional. Names are combined at random, so a generated name can
coincide with a real person. What guarantees the data can never be real is the identifiers,
emails, phone numbers and SSN-shaped values around the names (see tests/test_synthetic_guard.py).
"""

GIVEN_NAMES = (
    "Adaeze", "Amara", "Chidi", "Emeka", "Fatima", "Halima", "Ibrahim", "Kofi", "Ngozi", "Seun",
    "Tunde", "Zainab", "Maria", "Daniel", "Priya", "Wei", "Liam", "Sofia", "Omar", "Leila",
    "Mateo", "Yuki", "Anika", "Jonas", "Elena", "Samuel", "Grace", "Hassan", "Ines", "Noah",
    "Bola", "Kemi", "Idris", "Aisha", "Tariq", "Mei", "Lucas", "Amina", "Victor", "Nia",
)  # fmt: skip

FAMILY_NAMES = (
    "Okafor", "Adeyemi", "Bello", "Nwosu", "Danjuma", "Abara", "Mensah", "Haddad", "Singh", "Chen",
    "Garcia", "Novak", "Larsen", "Rossi", "Mbeki", "Osei", "Yusuf", "Kamara", "Petrov", "Silva",
    "Nakamura", "Hughes", "Ibe", "Salim", "Bianchi", "Dube", "Eze", "Farouk", "Gomez", "Hale",
    "Ito", "Jain", "Khan", "Lopez", "Moyo", "Nunez", "Obi", "Park", "Quinn", "Reyes",
)  # fmt: skip

REGIONS = ("north", "coast", "central")

FACILITY_PREFIXES = (
    "Baobab", "Harmattan", "Lakeshore", "Savanna", "Cedar Ridge", "Coral Bay",
    "Riverbend", "Highland", "Sunrise", "Meridian", "Palm Grove", "Stonebridge",
)  # fmt: skip

FACILITY_SUFFIXES = ("Clinic", "Medical Center", "Imaging", "Surgical Center", "Specialty Group")

RED_FLAG_PHRASES = (
    "Progressive neurological deficit noted on examination.",
    "Examination raises concern for an urgent underlying condition.",
)

MEMO_TOPICS = (
    "rotate service credentials",
    "restore the document index from backup",
    "drain a worker node",
    "renew internal certificates",
    "rotate the model gateway key",
    "review audit log retention",
)
