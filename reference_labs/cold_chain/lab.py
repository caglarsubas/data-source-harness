"""Metadata defining the deterministic cold-chain pilot."""

from __future__ import annotations

import json
from pathlib import Path

from data_source_harness.pack_factory import (
    DatasetBlueprint,
    FieldBlueprint,
    FieldKind,
    IndustryPackDefinition,
    MockDatasetGenerator,
)
from data_source_harness.scaffolding import ConnectorScaffold, ConnectorScaffolder

LAB_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = LAB_ROOT.parents[1]


def pack_definition() -> IndustryPackDefinition:
    return IndustryPackDefinition(
        "cold-chain-excursion-response",
        "1.0.0",
        20260827,
        (
            DatasetBlueprint(
                "shipments",
                4,
                (
                    FieldBlueprint("shipment_id", FieldKind.SEQUENCE, prefix="ship"),
                    FieldBlueprint(
                        "lane", FieldKind.CHOICE, values=("HAM-OSL", "RTM-PAR", "SIN-HKG")
                    ),
                    FieldBlueprint("maximum_celsius", FieldKind.CHOICE, values=("5", "8")),
                ),
            ),
            DatasetBlueprint(
                "containers",
                4,
                (
                    FieldBlueprint("container_id", FieldKind.SEQUENCE, prefix="container"),
                    FieldBlueprint(
                        "shipment_id",
                        FieldKind.REFERENCE,
                        reference_dataset="shipments",
                        reference_field="shipment_id",
                    ),
                    FieldBlueprint(
                        "commodity",
                        FieldKind.CHOICE,
                        values=("vaccines", "dairy", "fresh-produce"),
                    ),
                ),
            ),
            DatasetBlueprint(
                "sensor-readings",
                12,
                (
                    FieldBlueprint("reading_id", FieldKind.SEQUENCE, prefix="reading"),
                    FieldBlueprint(
                        "container_id",
                        FieldKind.REFERENCE,
                        reference_dataset="containers",
                        reference_field="container_id",
                    ),
                    FieldBlueprint(
                        "temperature_celsius", FieldKind.INTEGER, minimum=-2, maximum=14
                    ),
                    FieldBlueprint("observed_at", FieldKind.TIMESTAMP),
                ),
            ),
            DatasetBlueprint(
                "incidents",
                4,
                (
                    FieldBlueprint("incident_id", FieldKind.SEQUENCE, prefix="incident"),
                    FieldBlueprint(
                        "shipment_id",
                        FieldKind.REFERENCE,
                        reference_dataset="shipments",
                        reference_field="shipment_id",
                    ),
                    FieldBlueprint("severity", FieldKind.CHOICE, values=("low", "high")),
                    FieldBlueprint("status", FieldKind.CHOICE, values=("open", "resolved")),
                ),
            ),
        ),
    )


def generated_data() -> dict[str, tuple[dict[str, object], ...]]:
    return MockDatasetGenerator().generate(pack_definition())


def carrier_scaffold() -> ConnectorScaffold:
    document = json.loads((LAB_ROOT / "technology/carrier-api/openapi.json").read_text())
    return ConnectorScaffolder().from_openapi(
        document, connector_id="coldchain.carrier-api", version="0.1.0"
    )


def excursion_count() -> int:
    data = generated_data()
    shipment_by_id = {row["shipment_id"]: row for row in data["shipments"]}
    container_by_id = {row["container_id"]: row for row in data["containers"]}
    count = 0
    for reading in data["sensor-readings"]:
        container = container_by_id[reading["container_id"]]
        shipment = shipment_by_id[container["shipment_id"]]
        if int(reading["temperature_celsius"]) > int(shipment["maximum_celsius"]):
            count += 1
    return count
