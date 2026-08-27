import pytest

from data_source_harness.planning import (
    BoundedQueryPlanner,
    PlanDenied,
    PlanningConstraints,
    QueryIntent,
    RelationshipRef,
)


def constraints() -> PlanningConstraints:
    return PlanningConstraints(
        {
            "orders": frozenset({"order_id", "serial_number", "error_code"}),
            "installed": frozenset({"serial_number", "product_id"}),
        },
        frozenset({"orders.serial_number->installed.serial_number"}),
        2,
        100,
        2_000,
    )


def test_planner_emits_only_bounded_authorized_shape() -> None:
    intent = QueryIntent(
        "erp",
        ("orders", "installed"),
        {"orders": ("order_id", "serial_number"), "installed": ("product_id",)},
        {"orders": {"error_code": "E21"}},
        (RelationshipRef("orders", "serial_number", "installed", "serial_number"),),
        20,
        1_000,
        "covered E21 analysis",
    )
    plan = BoundedQueryPlanner().compile(intent, constraints())
    request = plan.to_query_request({"role": "quality"})
    assert request.limit == 20
    assert request.plan["relationships"] == ["orders.serial_number->installed.serial_number"]


@pytest.mark.parametrize(
    ("intent", "reason"),
    [
        (
            QueryIntent("erp", ("orders",), {"orders": ("customer_email",)}, {}, (), 20, 1000, "x"),
            "field_not_authorized",
        ),
        (
            QueryIntent(
                "erp",
                ("orders", "installed"),
                {"orders": ("order_id",), "installed": ("product_id",)},
                {},
                (RelationshipRef("orders", "order_id", "installed", "product_id"),),
                20,
                1000,
                "x",
            ),
            "relationship_not_authorized",
        ),
    ],
)
def test_planner_denies_fields_and_relationships(intent: QueryIntent, reason: str) -> None:
    with pytest.raises(PlanDenied, match=reason):
        BoundedQueryPlanner().compile(intent, constraints())


def test_filter_authorization_is_asset_qualified() -> None:
    intent = QueryIntent(
        "erp",
        ("orders", "installed"),
        {"orders": ("order_id",), "installed": ("product_id",)},
        {"installed": {"error_code": "E21"}},
        (),
        20,
        1000,
        "x",
    )
    with pytest.raises(PlanDenied, match="filter_field_not_authorized"):
        BoundedQueryPlanner().compile(intent, constraints())
