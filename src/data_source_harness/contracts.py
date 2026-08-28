"""Schema fixture validation and Phase-0 acceptance gate."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[2]


class ResourcePath(Protocol):
    name: str

    def is_dir(self) -> bool: ...

    def is_file(self) -> bool: ...

    def iterdir(self) -> Any: ...

    def joinpath(self, *descendants: str) -> ResourcePath: ...

    def open(self, mode: str = "r", *args: Any, **kwargs: Any) -> Any: ...


if (ROOT / "schemas/v1").is_dir():
    SCHEMA_DIR: ResourcePath = ROOT / "schemas/v1"
    FIXTURE_DIR: ResourcePath = ROOT / "tests/fixtures/contracts"
else:  # Installed-wheel path; all validation inputs are embedded package resources.
    package_resources = files("data_source_harness").joinpath("resources")
    SCHEMA_DIR = package_resources.joinpath("schemas", "v1")
    FIXTURE_DIR = package_resources.joinpath("contract-fixtures")


@dataclass(frozen=True)
class GateCheck:
    check_id: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class GateReport:
    phase: str
    passed: bool
    checks: tuple[GateCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _jsonschema() -> Any:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - packaging guard
        raise RuntimeError(
            "contract validation requires the runtime jsonschema dependency"
        ) from exc
    return jsonschema


def load_json(path: ResourcePath) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_contract_fixtures() -> tuple[GateCheck, ...]:
    jsonschema = _jsonschema()
    checks: list[GateCheck] = []
    schema_paths = sorted(
        (path for path in SCHEMA_DIR.iterdir() if path.name.endswith(".schema.json")),
        key=lambda path: path.name,
    )
    for schema_path in schema_paths:
        schema_name = schema_path.name.removesuffix(".schema.json")
        schema = load_json(schema_path)
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        )
        positives = sorted(
            (
                path
                for path in FIXTURE_DIR.joinpath("positive").iterdir()
                if path.name.startswith(f"{schema_name}.") and path.name.endswith(".json")
            ),
            key=lambda path: path.name,
        )
        negatives = sorted(
            (
                path
                for path in FIXTURE_DIR.joinpath("negative").iterdir()
                if path.name.startswith(f"{schema_name}.") and path.name.endswith(".json")
            ),
            key=lambda path: path.name,
        )
        if not positives or not negatives:
            checks.append(
                GateCheck(
                    f"schema.{schema_name}.fixtures", False, "positive/negative fixture missing"
                )
            )
            continue
        positive_errors = [
            f"{fixture.name}: {error.message}"
            for fixture in positives
            for error in validator.iter_errors(load_json(fixture))
        ]
        negatives_accepted = [
            fixture.name for fixture in negatives if validator.is_valid(load_json(fixture))
        ]
        details = positive_errors + [f"accepted invalid: {name}" for name in negatives_accepted]
        checks.append(
            GateCheck(
                f"schema.{schema_name}.fixtures",
                not details,
                "; ".join(details)
                if details
                else f"{len(positives)} valid, {len(negatives)} rejected",
            )
        )
    if not checks:
        checks.append(GateCheck("schema.present", False, "no schemas found"))
    return tuple(checks)


def validate_repository_artifacts() -> tuple[GateCheck, ...]:
    jsonschema = _jsonschema()
    targets = {
        "deployment.air-gapped": (
            "deployment-profile.schema.json",
            ROOT / "deployment/profiles/air-gapped.json",
        ),
        "deployment.self-hosted": (
            "deployment-profile.schema.json",
            ROOT / "deployment/profiles/self-hosted.json",
        ),
        "deployment.local-laptop": (
            "deployment-profile.schema.json",
            ROOT / "deployment/profiles/local-laptop.json",
        ),
        "reference-lab.example": (
            "reference-lab-manifest.schema.json",
            ROOT / "reference-labs/reference-lab-manifest.example.json",
        ),
    }
    checks: list[GateCheck] = []
    for check_id, (schema_name, document_path) in targets.items():
        schema = load_json(SCHEMA_DIR / schema_name)
        validator = jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        )
        errors = sorted(
            validator.iter_errors(load_json(document_path)), key=lambda item: list(item.path)
        )
        checks.append(
            GateCheck(
                check_id,
                not errors,
                "; ".join(error.message for error in errors) if errors else str(document_path),
            )
        )

    catalog = load_json(ROOT / "contracts/catalog.v1.json")
    owned = catalog.get("ownedContracts", [])
    names = [item.get("name") for item in owned]
    schema_paths = [ROOT / item.get("schema", "") for item in owned]
    checks.append(
        GateCheck(
            "catalog.unique-owned-contracts",
            len(names) == len(set(names)),
            f"owned={len(names)}",
        )
    )
    missing = [str(path) for path in schema_paths if not path.is_file()]
    checks.append(
        GateCheck(
            "catalog.schemas-resolve",
            not missing,
            "; ".join(missing) if missing else f"schemas={len(schema_paths)}",
        )
    )
    catalogued = {path.resolve() for path in schema_paths}
    available = {path.resolve() for path in SCHEMA_DIR.glob("*.schema.json")}
    checks.append(
        GateCheck(
            "catalog.covers-all-schemas",
            catalogued == available,
            f"catalogued={len(catalogued)}, available={len(available)}",
        )
    )

    release_set = load_json(ROOT / "compatibility/cross-plane-release-set.lock.json")
    components = release_set.get("components", [])
    component_names = [item.get("name") for item in components]
    revisions_valid = all(
        re.fullmatch(r"[0-9a-f]{40}", str(item.get("revision", ""))) for item in components
    )
    checks.append(
        GateCheck(
            "compatibility.exact-revisions",
            len(components) == 4
            and len(component_names) == len(set(component_names))
            and revisions_valid,
            f"components={len(components)}",
        )
    )
    return tuple(checks)


def run_phase0_gate() -> GateReport:
    schema_checks = validate_contract_fixtures()
    required = {
        "contracts/catalog.v1.json",
        "compatibility/cross-plane-release-set.lock.json",
        "deployment/profiles/air-gapped.json",
        "deployment/profiles/local-laptop.json",
        "docs/architecture/phase-0.md",
        "docs/development-roadmap.md",
        "docs/security/threat-model.md",
        "docs/testing/phase-0-gates.md",
    }
    artifact_checks = tuple(
        GateCheck(f"artifact.{path}", (ROOT / path).is_file(), path) for path in sorted(required)
    )
    checks = schema_checks + artifact_checks + validate_repository_artifacts()
    return GateReport("phase-0", all(check.passed for check in checks), checks)
