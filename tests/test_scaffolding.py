from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from data_source_harness.scaffolding import ConnectorScaffolder

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


OPENAPI = {
    "openapi": "3.1.0",
    "paths": {
        "/shipments": {"get": {"operationId": "listShipments"}},
        "/shipments/{id}": {"get": {"operationId": "getShipment"}},
    },
}


def test_openapi_scaffold_is_deterministic_compilable_and_contract_valid() -> None:
    scaffolder = ConnectorScaffolder()
    first = scaffolder.from_openapi(OPENAPI, connector_id="coldchain.carrier-api")
    second = scaffolder.from_openapi(OPENAPI, connector_id="coldchain.carrier-api")
    assert first.files == second.files
    assert first.operations == ("getShipment", "listShipments")
    compile(first.files["connector.py"], "connector.py", "exec")
    profile = json.loads(first.files["connector-profile.json"])
    schema = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/data-source-connector-profile.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(schema).validate(profile)


def test_openapi_without_operations_is_rejected() -> None:
    with pytest.raises(ValueError, match="no operations"):
        ConnectorScaffolder().from_openapi(
            {"openapi": "3.1.0", "paths": {}}, connector_id="empty.api"
        )


def test_openapi_scaffold_separates_query_and_mutation_inventory() -> None:
    scaffold = ConnectorScaffolder().from_openapi(
        {
            "openapi": "3.1.0",
            "paths": {
                "/orders": {
                    "get": {"operationId": "listOrders"},
                    "post": {"operationId": "createOrder"},
                }
            },
        },
        connector_id="lab.orders",
    )
    profile = json.loads(scaffold.files["connector-profile.json"])
    catalog = json.loads(scaffold.files["operation-catalog.json"])["operations"]
    assert profile["capabilities"] == ["describe", "discover", "mutate", "query"]
    assert {(item["operationId"], item["capability"]) for item in catalog} == {
        ("listOrders", "query"),
        ("createOrder", "mutate"),
    }
    assert b"Mutation operations are inventory only" in scaffold.files["README.md"]


def test_openapi_scaffold_rejects_duplicate_or_invalid_operations() -> None:
    with pytest.raises(ValueError, match="unique"):
        ConnectorScaffolder().from_openapi(
            {
                "openapi": "3.1.0",
                "paths": {
                    "/a": {"get": {"operationId": "duplicate"}},
                    "/b": {"get": {"operationId": "duplicate"}},
                },
            },
            connector_id="lab.duplicate",
        )
    with pytest.raises(ValueError, match="OpenAPI 3.0/3.1"):
        ConnectorScaffolder().from_openapi(
            {"openapi": "2.0", "paths": {"/a": {"get": {}}}},
            connector_id="lab.invalid",
        )
