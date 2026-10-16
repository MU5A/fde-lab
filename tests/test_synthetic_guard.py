"""Guards that make it impossible for the generated data to be mistaken for real data."""

import re

from fde_lab.datagen import FILES

EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\w")
SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
PHONE = re.compile(r"\+1-\d{3}-\d{3}-\d{4}")
LONG_NUMBER = re.compile(r"(?<!\d)\d{13,19}(?!\d)")  # card-number shaped


def all_text(dataset_dir) -> str:
    return "\n".join((dataset_dir / name).read_text() for name in FILES)


def test_identifiers_are_prefixed(dataset):
    for key, field, prefix in (
        ("members", "member_id", "SYN-M-"),
        ("providers", "provider_id", "SYN-P-"),
        ("requests", "request_id", "SYN-R-"),
        ("documents", "doc_id", "SYN-D-"),
        ("users", "user_id", "SYN-U-"),
    ):
        assert all(row[field].startswith(prefix) for row in dataset[key]), key


def test_every_email_is_on_a_reserved_test_domain(dataset_dir):
    emails = EMAIL.findall(all_text(dataset_dir))
    assert emails
    assert all(e.endswith(".test") for e in emails), [e for e in emails if not e.endswith(".test")]


def test_every_ssn_shaped_value_is_in_the_never_issued_9xx_range(dataset_dir):
    ssns = SSN.findall(all_text(dataset_dir))
    assert ssns
    assert all(s.startswith("9") for s in ssns)


def test_every_phone_is_in_the_reserved_fictional_range(dataset_dir):
    phones = PHONE.findall(all_text(dataset_dir))
    assert phones
    assert all(re.fullmatch(r"\+1-202-555-01\d\d", p) for p in phones)


def test_no_card_shaped_numbers(dataset_dir):
    assert LONG_NUMBER.findall(all_text(dataset_dir)) == []


def test_codes_are_not_real_coding_systems(dataset):
    """Procedure and diagnosis codes use invented PX-/DX- prefixes, not CPT or ICD formats."""
    assert all(r["procedure_code"].startswith("PX-") for r in dataset["requests"])
    assert all(r["diagnosis_code"].startswith("DX-") for r in dataset["requests"])
