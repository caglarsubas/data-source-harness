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
        if not isinstance(openapi_version, str) or not isinstance(paths, Mapping):
            raise ValueError("an OpenAPI version and paths mapping are required")
        operations: list[str] = []
        for path, path_item in sorted(paths.items()):
            if not isinstance(path_item, Mapping):
                continue
            for method, operation in sorted(path_item.items()):
                if method.lower() not in self._verbs or not isinstance(operation, Mapping):
                    continue
                operation_id = operation.get("operationId")
                operations.append(str(operation_id or f"{method}_{path}"))
        if not operations:
            raise ValueError("OpenAPI document exposes no operations")

        profile = {
            "schemaVersion": "data.harness/v1",
            "kind": "DataSourceConnectorProfile",
            "connectorId": connector_id,
            "version": version,
            "sdkApi": "harness.connector/v1",
            "runtimeMode": "process",
            "dataModels": ["tabular"],
            "capabilities": ["discover", "describe", "query"],
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
            "URL or secret; bind both through the deployment credential-reference mechanism.\n"
        )
        files = {
            "connector-profile.json": (
                json.dumps(profile, indent=2, sort_keys=True) + "\n"
            ).encode(),
            "connector.py": source.encode(),
            "README.md": readme.encode(),
        }
        return ConnectorScaffold(connector_id, tuple(sorted(operations)), files)
