from collections import Counter

from fde_lab.datagen.acl import ROLES, can_read, role_from_groups


def users_by_label(dataset) -> dict:
    return {
        u["username"].removeprefix("syn.").removesuffix("@acme.test"): u for u in dataset["users"]
    }


def test_idp_groups_map_to_the_declared_role_and_region(dataset):
    for user in dataset["users"]:
        assert len(user["groups"]) == 1
        assert role_from_groups(user["groups"]) == (user["role"], user["region"]), user["username"]


def test_every_role_is_represented(dataset):
    assert {u["role"] for u in dataset["users"]} == set(ROLES)


def test_reviewers_read_only_their_own_regions_clinical_notes(dataset):
    users = users_by_label(dataset)
    north = users["reviewer.north.1"]
    for doc in (d for d in dataset["documents"] if d["doc_type"] == "clinical_note"):
        assert can_read(north, doc) == (doc["tenant"] == "north"), doc["doc_id"]


def test_medical_directors_read_every_clinical_note_and_memo(dataset):
    md = users_by_label(dataset)["md.1"]
    for doc in dataset["documents"]:
        if doc["doc_type"] in ("clinical_note", "exception_memo", "policy"):
            assert can_read(md, doc), doc["doc_id"]


def test_nobody_but_medical_directors_reads_exception_memos(dataset):
    memos = [d for d in dataset["documents"] if d["doc_type"] == "exception_memo"]
    for user in dataset["users"]:
        for memo in memos:
            assert can_read(user, memo) == (user["role"] == "medical_director")


def test_claims_analysts_and_admins_never_read_clinical_notes(dataset):
    notes = [d for d in dataset["documents"] if d["doc_type"] == "clinical_note"]
    for user in dataset["users"]:
        if user["role"] in ("claims_analyst", "admin"):
            assert not any(can_read(user, n) for n in notes), user["username"]


def test_admins_read_only_policies_and_runbooks(dataset):
    admin = users_by_label(dataset)["admin.1"]
    readable = {d["doc_type"] for d in dataset["documents"] if can_read(admin, d)}
    assert readable == {"policy", "it_runbook"}


def test_every_user_can_read_something(dataset):
    for user in dataset["users"]:
        assert any(can_read(user, d) for d in dataset["documents"]), user["username"]


def test_restricted_documents_carry_unique_canaries(dataset):
    restricted = [d for d in dataset["documents"] if d["doc_type"] != "policy"]
    canaries = [d["canary"] for d in restricted]
    assert all(c and c in d["body"] for c, d in zip(canaries, restricted, strict=True))
    assert len(set(canaries)) == len(canaries)
    assert all(d["canary"] is None for d in dataset["documents"] if d["doc_type"] == "policy")


def test_canaries_appear_in_no_other_document(dataset):
    for doc in dataset["documents"]:
        if doc["canary"]:
            holders = [d["doc_id"] for d in dataset["documents"] if doc["canary"] in d["body"]]
            assert holders == [doc["doc_id"]]


def test_clinical_notes_inherit_the_members_region(dataset):
    members = {m["member_id"]: m for m in dataset["members"]}
    requests = {r["request_id"]: r for r in dataset["requests"]}
    notes = [d for d in dataset["documents"] if d["doc_type"] == "clinical_note"]
    assert len(notes) == 60
    for note in notes:
        member = members[requests[note["ref_request_id"]]["member_id"]]
        assert note["tenant"] == member["region"]


def test_regions_are_all_used(dataset):
    assert Counter(m["region"] for m in dataset["members"]).keys() == {"north", "coast", "central"}
