"""Reference tables for the fictional Acme Health Plan.

Procedure codes (PX-), diagnosis codes (DX-) and plan ids are invented. They are not CPT,
ICD or any real coding system, so nothing here can be mistaken for real clinical data.
"""

from __future__ import annotations

from dataclasses import dataclass

AS_OF = "2026-10-01"
APPROVAL_THRESHOLD = 10_000  # approval recommendations at or above this need a human approver


@dataclass(frozen=True)
class Procedure:
    code: str
    name: str
    category: str
    auth_required: bool
    base_cost: int
    therapy_days_required: int
    weight: int  # relative sampling frequency


@dataclass(frozen=True)
class Plan:
    plan_id: str
    name: str
    annual_limit: int
    excluded_codes: tuple[str, ...]
    weight: int


PROCEDURES = (
    Procedure("PX-1001", "Lumbar spine MRI", "imaging", True, 1_400, 42, 22),
    Procedure("PX-1002", "Knee MRI", "imaging", True, 1_300, 28, 16),
    Procedure("PX-1003", "Total knee replacement", "surgery", True, 38_000, 90, 6),
    Procedure("PX-1004", "Lumbar fusion", "surgery", True, 78_000, 180, 3),
    Procedure("PX-1005", "In-lab sleep study", "diagnostic", True, 2_200, 0, 9),
    Procedure(
        "PX-1006", "Outpatient physical therapy, 12 sessions", "therapy", False, 1_800, 0, 12
    ),
    Procedure("PX-1007", "Cataract surgery", "surgery", True, 4_800, 0, 8),
    Procedure("PX-1008", "Cardiac stress test", "diagnostic", False, 900, 0, 7),
    Procedure("PX-1009", "Biologic infusion, rheumatoid arthritis", "drug", True, 22_000, 90, 5),
    Procedure("PX-1010", "Hereditary cancer genetic panel", "lab", True, 3_900, 0, 4),
)

PLANS = (
    Plan("PLN-BASIC", "Acme Basic", 30_000, ("PX-1003", "PX-1004", "PX-1009", "PX-1010"), 45),
    Plan("PLN-STANDARD", "Acme Standard", 80_000, ("PX-1010",), 40),
    Plan("PLN-PREMIUM", "Acme Premium", 250_000, (), 15),
)

DIAGNOSES = {
    "PX-1001": (("DX-101", "chronic low back pain"), ("DX-102", "lumbar radiculopathy")),
    "PX-1002": (("DX-111", "knee pain"), ("DX-112", "suspected meniscal injury")),
    "PX-1003": (("DX-121", "advanced knee osteoarthritis"),),
    "PX-1004": (("DX-131", "lumbar spinal stenosis"), ("DX-132", "degenerative disc disease")),
    "PX-1005": (("DX-141", "suspected obstructive sleep apnea"),),
    "PX-1006": (("DX-151", "post-operative rehabilitation"), ("DX-152", "chronic neck pain")),
    "PX-1007": (("DX-161", "visually significant cataract"),),
    "PX-1008": (("DX-171", "exertional chest discomfort"),),
    "PX-1009": (("DX-181", "rheumatoid arthritis with inadequate response to first-line therapy"),),
    "PX-1010": (("DX-191", "family history of a hereditary cancer syndrome"),),
}
