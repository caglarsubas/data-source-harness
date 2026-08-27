"""Generate auditable connector starter artifacts from OpenAPI metadata."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConnectorScaffold:
    connector_id: str
    operations: tuple[str, ...]
    files: Mapping[str, bytes]


class ConnectorScaffolder:
    """Produce deterministic source and a v1 connector profile without executing input."""

    _verbs = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
    _read_verbs = frozenset({"get", "head", "options"})

    def from_openapi(
        self,
        document: Mapping[str, Any],
        *,
        connector_id: str,
        version: str = "0.1.0",
    ) -> ConnectorScaffold:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]+", connector_id):
            raise ValueError("connector_id must satisfy the public connector profile contract")
        openapi_version = document.get("openapi")
        paths = document.get("paths")
        if (
            not isinstance(openapi_version, str)
            or not re.fullmatch(r"3\.(?:0|1)\.\d+", openapi_version)
            or not isinstance(paths, Mapping)
        ):
            raise ValueError("an OpenAPI 3.0/3.1 version and paths mapping are required")
        operations: list[str] = []
        catalog: list[dict[str, str]] = []
        for path, path_item in sorted(paths.items()):
            if (
                not isinstance(path, str)
                or not path.startswith("/")
                or not isinstance(path_item, Mapping)
            ):
                raise ValueError("OpenAPI paths must be absolute strings with path objects")
            for method, operation in sorted(path_item.items()):
                if method.lower() not in self._verbs or not isinstance(operation, Mapping):
                    continue
                operation_id = operation.get("operationId")
                if operation_id is None:
                    operation_id = re.sub(r"[^A-Za-z0-9]+", "_", f"{method}_{path}").strip("_")
                    operation_id = operation_id or method.lower()
                if not isinstance(operation_id, str) or not re.fullmatch(
                    r"[A-Za-z][A-Za-z0-9_.-]{0,127}", operation_id
                ):
                    raise ValueError("OpenAPI operationId values must be bounded identifiers")
                verb = method.lower()
                capability = "query" if verb in self._read_verbs else "mutate"
                operations.append(operation_id)
                catalog.append(
                    {
                        "operationId": operation_id,
                        "method": verb.upper(),
                        "path": path,
                        "capability": capability,
                    }
                )
        if not operations:
            raise ValueError("OpenAPI document exposes no operations")
        if len(operations) != len(set(operations)):
            raise ValueError("OpenAPI operationId values must be unique")

        advertised_capabilities = {"discover", "describe"}
        advertised_capabilities.update(item["capability"] for item in catalog)

        profile = {
            "schemaVersion": "data.harness/v1",
            "kind": "DataSourceConnectorProfile",
            "connectorId": connector_id,
            "version": version,
            "sdkApi": "harness.connector/v1",
            "runtimeMode": "process",
            "dataModels": ["tabular"],
            "capabilities": sorted(advertised_capabilities),
            "authMethods": ["credential-reference"],
            "limits": {
                "maxParallelism": 4,
                "maxResultBytes": 10485760,
                "supportsCancellation": True,
            },
            "consistency": {
                "readIsolation": ["remote-api-snapshot"],
                "supportsTransactions": False,
                "supportsCheckpoint": False,
                "supportsCdc": False,
            },
        }
        constant = json.dumps(sorted(operations), separators=(",", ":"))
        source = (
            '"""Generated adapter; transport and credentials are deployment supplied."""\n\n'
            f"CONNECTOR_ID = {connector_id!r}\n"
            f"OPENAPI_VERSION = {openapi_version!r}\n"
            f"OPERATIONS = tuple({constant})\n\n"
            "def supports(operation_id: str) -> bool:\n"
            "    return operation_id in OPERATIONS\n"
        )
        readme = (
            f"# {connector_id}\n\n"
            "Generated from OpenAPI metadata. The scaffold deliberately contains no endpoint "
            "URL or secret; bind both through the deployment credential-reference mechanism.\n\n"
            "Mutation operations are inventory only until an explicit action profile, policy, "
            "preview, idempotency, precondition and compensation design is supplied.\n"
        )
        files = {
            "connector-profile.json": (
                json.dumps(profile, indent=2, sort_keys=True) + "\n"
            ).encode(),
            "connector.py": source.encode(),
            "operation-catalog.json": (
                json.dumps({"operations": catalog}, indent=2, sort_keys=True) + "\n"
            ).encode(),
            "README.md": readme.encode(),
        }
        return ConnectorScaffold(connector_id, tuple(sorted(operations)), files)
