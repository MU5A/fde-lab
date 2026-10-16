from collections import Counter

import pytest

from fde_lab.datagen.reference import APPROVAL_THRESHOLD, PLANS, PROCEDURES
from fde_lab.datagen.rules import REASONS, ROUTES, RoutingInput, route

PROC = {p.code: p for p in PROCEDURES}
PLAN = {p.plan_id: p for p in PLANS}


def case(**overrides) -> RoutingInput:
    base = {
        "procedure": PROC["PX-1001"],  # lumbar MRI, needs 42 days
        "plan": PLAN["PLN-STANDARD"],
        "member_active": True,
        "ytd_spend": 0,
        "cost_estimate": 1_400,
        "urgency": "routine",
        "therapy_days": 42,
        "red_flag": False,
        "docs_complete": True,
    }
    base.update(overrides)
    return RoutingInput(**base)


def test_the_system_never_denies():
    assert not any("DENY" in r or "DENIED" in r for r in ROUTES + REASONS)


def test_therapy_boundary():
    assert route(case(therapy_days=41)).reason == "CONSERVATIVE_THERAPY_NOT_MET"
    assert route(case(therapy_days=42)).route == "APPROVE_RECOMMENDED"


def test_human_approval_threshold_boundary():
    knee = PROC["PX-1003"]
    at = route(
        case(
            procedure=knee,
            plan=PLAN["PLN-PREMIUM"],
            cost_estimate=APPROVAL_THRESHOLD,
            therapy_days=90,
        )
    )
    below = route(
        case(
            procedure=knee,
            plan=PLAN["PLN-PREMIUM"],
            cost_estimate=APPROVAL_THRESHOLD - 10,
            therapy_days=90,
        )
    )
    assert at.requires_human_approval is True
    assert below.requires_human_approval is False


def test_annual_limit_boundary():
    limit = PLAN["PLN-STANDARD"].annual_limit
    assert route(case(ytd_spend=limit - 1_400)).route == "APPROVE_RECOMMENDED"
    assert route(case(ytd_spend=limit - 1_399)).reason == "ANNUAL_LIMIT_EXCEEDED"


def test_urgent_red_flag_skips_the_therapy_requirement_but_still_goes_to_a_clinician():
    result = route(case(therapy_days=0, urgency="urgent", red_flag=True))
    assert (result.route, result.reason, result.expedite) == (
        "CLINICAL_REVIEW",
        "RED_FLAG_EXPEDITE",
        True,
    )


def test_routine_red_flag_does_not_expedite():
    result = route(case(therapy_days=0, urgency="routine", red_flag=True))
    assert result.reason == "CONSERVATIVE_THERAPY_NOT_MET"
    assert result.expedite is False


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        # a procedure that needs no authorization wins over everything else
        ({"procedure": PROC["PX-1006"], "member_active": False}, "AUTH_NOT_REQUIRED"),
        # an inactive member beats a plan exclusion
        ({"member_active": False, "procedure": PROC["PX-1010"]}, "INACTIVE_MEMBER"),
        # coverage problems beat missing documentation
        ({"procedure": PROC["PX-1010"], "docs_complete": False}, "EXCLUDED_BY_PLAN"),
        # missing documentation beats an unmet therapy requirement
        ({"docs_complete": False, "therapy_days": 0}, "MISSING_DOCUMENTATION"),
    ],
)
def test_rule_precedence(overrides, expected):
    assert route(case(**overrides)).reason == expected


def test_routes_match_the_rules_for_every_generated_request(dataset):
    members = {m["member_id"]: m for m in dataset["members"]}
    requests = {r["request_id"]: r for r in dataset["requests"]}
    for t in dataset["truth"]:
        req = requests[t["request_id"]]
        member = members[req["member_id"]]
        recomputed = route(
            RoutingInput(
                procedure=PROC[req["procedure_code"]],
                plan=PLAN[member["plan_id"]],
                member_active=t["member_active"],
                ytd_spend=member["ytd_spend"],
                cost_estimate=req["cost_estimate"],
                urgency=req["urgency"],
                therapy_days=t["truth"]["therapy_days"],
                red_flag=t["truth"]["red_flag"],
                docs_complete=t["truth"]["docs_complete"],
            )
        )
        assert (recomputed.route, recomputed.reason) == (t["route"], t["reason"]), t["request_id"]


def test_every_reason_has_enough_cases_to_evaluate(dataset):
    """A rule exercised only a handful of times cannot be evaluated, so each needs coverage."""
    counts = Counter(t["reason"] for t in dataset["truth"])
    assert set(counts) == set(REASONS)
    assert min(counts.values()) >= 20, counts


def test_every_route_is_between_5_and_60_percent(dataset):
    counts = Counter(t["route"] for t in dataset["truth"])
    total = sum(counts.values())
    for name in ROUTES:
        assert 0.05 <= counts[name] / total <= 0.60, (name, counts)


def test_notes_state_the_therapy_duration_that_the_truth_records(dataset):
    """The text a model will read must agree with the truth it is graded against."""
    requests = {r["request_id"]: r for r in dataset["requests"]}
    checked = 0
    for t in dataset["truth"]:
        note = requests[t["request_id"]]["note"]
        days = t["truth"]["therapy_days"]
        proc = PROC[requests[t["request_id"]]["procedure_code"]]
        if t["truth"]["docs_complete"] and proc.therapy_days_required > 0 and days > 0:
            weeks = days // 7
            assert (f"{days} days" in note) or (days % 7 == 0 and f"{weeks} weeks" in note)
            checked += 1
    assert checked > 200
