"""Approved Metabase question registry.

Only server-side registered question IDs are executable. Browser clients
cannot supply arbitrary Metabase question IDs, SQL, or query plans.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MetabaseQuestion:
    question_id: int
    name: str
    description: str
    collection_id: int | None
    database_id: int
    allowed_roles: list[str]
    allowed_filters: list[str]
    allowed_customer_types: list[str]
    # Every approved question is tenant-filtered. More restrictive scope
    # dimensions are required automatically for scoped roles/accounts.
    required_scope_filters: list[str] | None = None
    supports_csv: bool = True

    def __post_init__(self) -> None:
        if self.required_scope_filters is None:
            self.required_scope_filters = ["tenant_id"]
        if "tenant_id" not in self.required_scope_filters:
            raise ValueError("Approved Metabase questions must require tenant_id")
        missing = set(self.required_scope_filters) - set(self.allowed_filters)
        if missing:
            raise ValueError(
                f"Required scope filters are not allowed: {sorted(missing)}"
            )


APPROVED_QUESTIONS: dict[int, MetabaseQuestion] = {}


def register_question(question: MetabaseQuestion) -> None:
    if question.question_id <= 0:
        raise ValueError("Metabase question_id must be positive")
    APPROVED_QUESTIONS[question.question_id] = question


def get_question(question_id: int) -> MetabaseQuestion | None:
    return APPROVED_QUESTIONS.get(question_id)


def is_approved(question_id: int) -> bool:
    return question_id in APPROVED_QUESTIONS


def list_approved_questions() -> list[MetabaseQuestion]:
    return list(APPROVED_QUESTIONS.values())


def get_question_by_name(name: str) -> MetabaseQuestion | None:
    for q in APPROVED_QUESTIONS.values():
        if q.name.casefold() == name.casefold():
            return q
    return None


# Phase 1 Registered Questions
# Local Metabase database ID = 4 (DOU Local Demo)

register_question(
    MetabaseQuestion(
        question_id=60,
        name="Total Riders",
        description="Total riders in tenant scope",
        collection_id=None,
        database_id=4,
        allowed_roles=[
            "COMPANY",
            "COMPANY_ADMIN",
            "OPERATIONS",
            "HR",
            "ACCOUNTANT",
            "VIEWER",
            "SUPERVISOR",
            "PROJECT_MANAGER",
        ],
        allowed_filters=["tenant_id"],
        allowed_customer_types=["LOGISTICS_OPERATOR", "DELIVERY_PLATFORM"],
    )
)

register_question(
    MetabaseQuestion(
        question_id=61,
        name="Active Riders",
        description="Active riders in tenant scope",
        collection_id=None,
        database_id=4,
        allowed_roles=[
            "COMPANY",
            "COMPANY_ADMIN",
            "OPERATIONS",
            "HR",
            "ACCOUNTANT",
            "VIEWER",
            "SUPERVISOR",
            "PROJECT_MANAGER",
        ],
        allowed_filters=["tenant_id"],
        allowed_customer_types=["LOGISTICS_OPERATOR", "DELIVERY_PLATFORM"],
    )
)

register_question(
    MetabaseQuestion(
        question_id=62,
        name="Attendance Rate",
        description="Weekly attendance rate by tenant",
        collection_id=None,
        database_id=4,
        allowed_roles=[
            "COMPANY",
            "COMPANY_ADMIN",
            "OPERATIONS",
            "HR",
            "ACCOUNTANT",
            "VIEWER",
            "SUPERVISOR",
            "PROJECT_MANAGER",
        ],
        allowed_filters=["tenant_id"],
        allowed_customer_types=["LOGISTICS_OPERATOR", "DELIVERY_PLATFORM"],
    )
)

register_question(
    MetabaseQuestion(
        question_id=63,
        name="Top Performers",
        description="Top performers by achievement percentage",
        collection_id=None,
        database_id=4,
        allowed_roles=[
            "COMPANY",
            "COMPANY_ADMIN",
            "OPERATIONS",
            "HR",
            "ACCOUNTANT",
            "VIEWER",
            "SUPERVISOR",
            "PROJECT_MANAGER",
        ],
        allowed_filters=["tenant_id"],
        allowed_customer_types=["LOGISTICS_OPERATOR", "DELIVERY_PLATFORM"],
    )
)

register_question(
    MetabaseQuestion(
        question_id=64,
        name="Capacity Shortage",
        description="Active shifts with capacity shortage",
        collection_id=None,
        database_id=4,
        allowed_roles=[
            "COMPANY",
            "COMPANY_ADMIN",
            "OPERATIONS",
            "HR",
            "ACCOUNTANT",
            "VIEWER",
            "SUPERVISOR",
            "PROJECT_MANAGER",
        ],
        allowed_filters=["tenant_id"],
        allowed_customer_types=["LOGISTICS_OPERATOR", "DELIVERY_PLATFORM"],
    )
)

register_question(
    MetabaseQuestion(
        question_id=65,
        name="Expiring Documents",
        description="Documents expiring within 60 days",
        collection_id=None,
        database_id=4,
        allowed_roles=[
            "COMPANY",
            "COMPANY_ADMIN",
            "OPERATIONS",
            "HR",
            "ACCOUNTANT",
            "VIEWER",
            "SUPERVISOR",
            "PROJECT_MANAGER",
        ],
        allowed_filters=["tenant_id"],
        allowed_customer_types=["LOGISTICS_OPERATOR", "DELIVERY_PLATFORM"],
    )
)

register_question(
    MetabaseQuestion(
        question_id=66,
        name="Payroll Summary",
        description="Payroll periods by month and status",
        collection_id=None,
        database_id=4,
        allowed_roles=["COMPANY", "COMPANY_ADMIN", "OPERATIONS", "HR", "ACCOUNTANT"],
        allowed_filters=["tenant_id"],
        allowed_customer_types=["LOGISTICS_OPERATOR", "DELIVERY_PLATFORM"],
    )
)

register_question(
    MetabaseQuestion(
        question_id=67,
        name="Target Achievement",
        description="Average achievement by target type",
        collection_id=None,
        database_id=4,
        allowed_roles=[
            "COMPANY",
            "COMPANY_ADMIN",
            "OPERATIONS",
            "HR",
            "ACCOUNTANT",
            "VIEWER",
            "SUPERVISOR",
            "PROJECT_MANAGER",
        ],
        allowed_filters=["tenant_id"],
        allowed_customer_types=["LOGISTICS_OPERATOR", "DELIVERY_PLATFORM"],
    )
)
