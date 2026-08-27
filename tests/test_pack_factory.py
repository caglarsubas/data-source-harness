from __future__ import annotations

import pytest

from data_source_harness.pack_factory import (
    DatasetBlueprint,
    FieldBlueprint,
    FieldKind,
    IndustryPackDefinition,
    MockDatasetGenerator,
)


def _definition() -> IndustryPackDefinition:
    return IndustryPackDefinition(
        "test-pack",
        "1.0.0",
        42,
        (
            DatasetBlueprint(
                "parents",
                3,
                (
                    FieldBlueprint("parent_id", FieldKind.SEQUENCE, prefix="parent"),
                    FieldBlueprint("kind", FieldKind.CHOICE, values=("a", "b")),
                ),
            ),
            DatasetBlueprint(
                "children",
                5,
                (
                    FieldBlueprint("child_id", FieldKind.SEQUENCE, prefix="child"),
                    FieldBlueprint(
                        "parent_id",
                        FieldKind.REFERENCE,
                        reference_dataset="parents",
                        reference_field="parent_id",
                    ),
                    FieldBlueprint("reading", FieldKind.INTEGER, minimum=1, maximum=9),
                    FieldBlueprint("observed_at", FieldKind.TIMESTAMP),
                ),
            ),
        ),
    )


def test_generation_is_deterministic_and_referentially_safe() -> None:
    generator = MockDatasetGenerator()
    first = generator.generate(_definition())
    second = generator.generate(_definition())
    assert first == second
    parent_ids = {row["parent_id"] for row in first["parents"]}
    assert {row["parent_id"] for row in first["children"]}.issubset(parent_ids)
    assert generator.render_jsonl(first["children"]) == generator.render_jsonl(second["children"])


def test_unknown_or_cyclic_reference_is_rejected() -> None:
    definition = IndustryPackDefinition(
        "broken-pack",
        "1",
        1,
        (
            DatasetBlueprint(
                "records",
                1,
                (
                    FieldBlueprint(
                        "missing_id",
                        FieldKind.REFERENCE,
                        reference_dataset="missing",
                        reference_field="id",
                    ),
                ),
            ),
        ),
    )
    with pytest.raises(ValueError, match="cyclic or unknown"):
        MockDatasetGenerator().generate(definition)


def test_weighted_and_nullable_fields_are_deterministic_and_representative() -> None:
    definition = IndustryPackDefinition(
        "weighted-pack",
        "1",
        7,
        (
            DatasetBlueprint(
                "events",
                1_000,
                (
                    FieldBlueprint("event_id", FieldKind.SEQUENCE, prefix="event"),
                    FieldBlueprint(
                        "outcome",
                        FieldKind.CHOICE,
                        values=("normal", "rare"),
                        weights=(99, 1),
                    ),
                    FieldBlueprint(
                        "optional_code",
                        FieldKind.CHOICE,
                        values=("A", "B"),
                        null_rate=0.2,
                    ),
                ),
            ),
        ),
    )
    first = MockDatasetGenerator().generate(definition)["events"]
    second = MockDatasetGenerator().generate(definition)["events"]
    assert first == second
    rare = sum(row["outcome"] == "rare" for row in first)
    missing = sum(row["optional_code"] is None for row in first)
    assert 1 <= rare < 50
    assert 100 <= missing <= 300


def test_invalid_distribution_blueprints_are_rejected() -> None:
    with pytest.raises(ValueError, match="weights"):
        FieldBlueprint(
            "outcome",
            FieldKind.CHOICE,
            values=("a", "b"),
            weights=(1,),
        )
    with pytest.raises(ValueError, match="null rate"):
        FieldBlueprint("value", FieldKind.INTEGER, null_rate=1.0)
