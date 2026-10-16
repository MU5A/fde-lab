"""The routing rules that define the gold labels for every synthetic pre-authorization request.

Design principle: the system never issues a denial. A request is either recommended for
approval, returned for more information, or sent to a human reviewer. Anything at or above
the approval threshold still needs a recorded human approver.
"""

from __future__ import annotations

from dataclasses import dataclass

from .reference import APPROVAL_THRESHOLD, Plan, Procedure

ROUTES = (
    "NO_AUTH_NEEDED",
    "APPROVE_RECOMMENDED",
    "NEEDS_INFO",
    "CLINICAL_REVIEW",
    "COVERAGE_REVIEW",
)

REASONS = (
    "AUTH_NOT_REQUIRED",
    "INACTIVE_MEMBER",
    "EXCLUDED_BY_PLAN",
    "ANNUAL_LIMIT_EXCEEDED",
    "MISSING_DOCUMENTATION",
    "RED_FLAG_EXPEDITE",
    "CONSERVATIVE_THERAPY_NOT_MET",
    "CRITERIA_MET",
)


@dataclass(frozen=True)
class RoutingInput:
    procedure: Procedure
    plan: Plan
    member_active: bool
    ytd_spend: int
    cost_estimate: int
    urgency: str
    therapy_days: int
    red_flag: bool
    docs_complete: bool


@dataclass(frozen=True)
class Routing:
    route: str
    reason: str
    requires_human_approval: bool
    expedite: bool


def route(i: RoutingInput) -> Routing:
    """Apply the rules in order. The first matching rule wins."""
    if not i.procedure.auth_required:
        return Routing("NO_AUTH_NEEDED", "AUTH_NOT_REQUIRED", False, False)
    if not i.member_active:
        return Routing("COVERAGE_REVIEW", "INACTIVE_MEMBER", False, False)
    if i.procedure.code in i.plan.excluded_codes:
        return Routing("COVERAGE_REVIEW", "EXCLUDED_BY_PLAN", False, False)
    if i.ytd_spend + i.cost_estimate > i.plan.annual_limit:
        return Routing("COVERAGE_REVIEW", "ANNUAL_LIMIT_EXCEEDED", False, False)
    if not i.docs_complete:
        return Routing("NEEDS_INFO", "MISSING_DOCUMENTATION", False, False)
    if i.red_flag and i.urgency == "urgent":
        return Routing("CLINICAL_REVIEW", "RED_FLAG_EXPEDITE", False, True)
    if i.therapy_days < i.procedure.therapy_days_required:
        return Routing("CLINICAL_REVIEW", "CONSERVATIVE_THERAPY_NOT_MET", False, False)
    return Routing(
        "APPROVE_RECOMMENDED",
        "CRITERIA_MET",
        i.cost_estimate >= APPROVAL_THRESHOLD,
        False,
    )
