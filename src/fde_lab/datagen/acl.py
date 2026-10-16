"""The access-control oracle for the synthetic dataset.

Later modules (the OIDC bridge, row-level security, permission-filtered retrieval) are tested
against these functions, so there is one definition of who may read what.
"""

from __future__ import annotations

from collections.abc import Iterable

ROLES = ("reviewer", "medical_director", "claims_analyst", "admin")

# Identity-provider group -> (role). Regional groups carry the region in the group name.
GLOBAL_GROUP_ROLES = {
    "acme-medical-directors": "medical_director",
    "acme-it-admins": "admin",
}
REGIONAL_GROUP_PREFIXES = {
    "acme-um-reviewers-": "reviewer",
    "acme-claims-analysts-": "claims_analyst",
}

DOC_TYPE_ROLES = {
    "policy": ROLES,
    "clinical_note": ("reviewer", "medical_director"),
    "exception_memo": ("medical_director",),
    "finance_note": ("claims_analyst",),
    "it_runbook": ("admin",),
}


def role_from_groups(groups: Iterable[str]) -> tuple[str, str]:
    """Return (role, region) for a set of IdP groups. Region is '*' for cross-region roles."""
    for group in groups:
        if group in GLOBAL_GROUP_ROLES:
            return GLOBAL_GROUP_ROLES[group], "*"
        for prefix, role in REGIONAL_GROUP_PREFIXES.items():
            if group.startswith(prefix):
                return role, group.removeprefix(prefix)
    raise ValueError(f"no recognised role group in {list(groups)}")


def can_read(user: dict, doc: dict) -> bool:
    """A user may read a document if their role is allowed and the tenant matches."""
    if user["role"] not in doc["allowed_roles"]:
        return False
    if doc["tenant"] == "*" or user["region"] == "*":
        return True
    return user["region"] == doc["tenant"]


REQUEST_READER_ROLES = ("reviewer", "medical_director")


def can_read_request(user: dict, member: dict) -> bool:
    """Pre-authorization requests carry clinical detail, so only clinicians may read them.

    Reviewers are limited to members in their own region. Claims analysts and administrators
    never read a request.
    """
    if user["role"] not in REQUEST_READER_ROLES:
        return False
    return user["region"] == "*" or user["region"] == member["region"]
