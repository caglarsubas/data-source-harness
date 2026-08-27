"""Machine-readable Phase-3 industry-pack factory certification."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import jsonschema

from data_source_harness.pack_factory import MockDatasetGenerator
from data_source_harness.packaging import (
    HmacSha256Signer,
    build_signed_package,
    verify_signed_package,
)
from reference_labs.white_goods.certify import CertificationCheck, MetricResult, _metric

from .lab import LAB_ROOT, REPOSITORY_ROOT, carrier_scaffold, excursion_count, generated_data

LAB_SIGNER = HmacSha256Signer("cold-chain-lab-key", b"cold-chain-reference-key-material")


@dataclass(frozen=True)
class Phase3Report:
    phase: str
    lab_id: str
    passed: bool
    checks: tuple[CertificationCheck, ...]
    metrics: tuple[MetricResult, ...]
    evidence_boundary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _manifest_checks() -> list[CertificationCheck]:
    checks: list[CertificationCheck] = []
    pairs = (
        ("industry-domain-pack-manifest.schema.json", "pack-manifest.json"),
        ("reference-lab-manifest.schema.json", "reference-lab-manifest.json"),
    )
    for schema_name, document_name in pairs:
        schema = json.loads((REPOSITORY_ROOT / "schemas/v1" / schema_name).read_text())
        document = json.loads((LAB_ROOT / document_name).read_text())
        errors = list(jsonschema.Draft202012Validator(schema).iter_errors(document))
        checks.append(
            CertificationCheck(
                f"manifest.{document_name}",
                not errors,
                "; ".join(error.message for error in errors) if errors else "valid",
            )
        )
    return checks


def _schema_reuse() -> tuple[bool, str]:
    lock = json.loads(
        (REPOSITORY_ROOT / "compatibility/phase2-core-contracts.lock.json").read_text()
    )
    evolution = json.loads(
        (REPOSITORY_ROOT / "compatibility/phase2-contract-evolution.json").read_text()
    )
    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((REPOSITORY_ROOT / "schemas/v1").glob("*.json"))
    }
    locked = lock["schemas"]
    entries = {item["schema"]: item for item in evolution["entries"]}
    changed = {name for name, digest in locked.items() if actual.get(name) != digest}
    approved = changed == set(entries) and all(
        entry["baselineSha256"] == locked[name]
        and entry["currentSha256"] == actual.get(name)
        and entry["backwardCompatible"] is True
        and bool(entry["reason"])
        for name, entry in entries.items()
    )
    compatible = set(locked) <= set(actual) and approved
    return (
        compatible,
        f"baseline={len(locked)}; unchanged={len(locked) - len(changed)}; evolved={len(changed)}",
    )


def _core_leakage() -> tuple[int, str]:
    forbidden = ("whitegoods", "white_goods", "white-goods", "washing-machine", "e21")
    findings: list[str] = []
    for path in sorted((REPOSITORY_ROOT / "src/data_source_harness").glob("*.py")):
        lowered = path.read_text(encoding="utf-8").lower()
        findings.extend(f"{path.name}:{token}" for token in forbidden if token in lowered)
    return len(findings), ",".join(findings) if findings else "none"


def certify_phase3() -> Phase3Report:
    checks = _manifest_checks()
    plan = json.loads((LAB_ROOT / "phase3-gqm-plan.json").read_text())
    definitions = {item["metricId"]: item for item in plan["metrics"]}
    generator = MockDatasetGenerator()
    first = generated_data()
    second = generated_data()
    deterministic = first == second
    fixtures_match = all(
        (LAB_ROOT / "data" / f"{dataset_id}.jsonl").read_bytes() == generator.render_jsonl(records)
        for dataset_id, records in first.items()
    )
    shipment_ids = {row["shipment_id"] for row in first["shipments"]}
    container_ids = {row["container_id"] for row in first["containers"]}
    references_valid = (
        {row["shipment_id"] for row in first["containers"]}.issubset(shipment_ids)
        and {row["shipment_id"] for row in first["incidents"]}.issubset(shipment_ids)
        and {row["container_id"] for row in first["sensor-readings"]}.issubset(container_ids)
    )
    checks.append(
        CertificationCheck(
            "factory.deterministic-locked-fixtures",
            deterministic and fixtures_match,
            f"datasets={len(first)}; fixtures_match={fixtures_match}",
        )
    )
    checks.append(
        CertificationCheck(
            "factory.referential-integrity", references_valid, "all foreign references resolve"
        )
    )

    scaffold = carrier_scaffold()
    source_compiles = True
    try:
        compile(scaffold.files["connector.py"], "connector.py", "exec")
    except SyntaxError:
        source_compiles = False
    operation_coverage = len(scaffold.operations) == 3
    profile_schema = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/data-source-connector-profile.schema.json").read_text()
    )
    profile_errors = list(
        jsonschema.Draft202012Validator(profile_schema).iter_errors(
            json.loads(scaffold.files["connector-profile.json"])
        )
    )
    checks.append(
        CertificationCheck(
            "scaffold.openapi-profile-and-source",
            operation_coverage and source_compiles and not profile_errors,
            f"operations={len(scaffold.operations)}; compiles={source_compiles}",
        )
    )

    with tempfile.TemporaryDirectory() as directory:
        package = Path(directory) / "carrier-connector.zip"
        digest = build_signed_package(
            package,
            scaffold.files,
            LAB_SIGNER,
            component_name=scaffold.connector_id,
            component_version="0.1.0",
        )
        signature_ok = verify_signed_package(package, LAB_SIGNER) == digest
        wrong_key_denied = False
        try:
            verify_signed_package(
                package,
                HmacSha256Signer("wrong-key", b"wrong-but-long-reference-material"),
            )
        except ValueError:
            wrong_key_denied = True
        tampered = Path(directory) / "tampered.zip"
        with zipfile.ZipFile(package) as source, zipfile.ZipFile(tampered, "w") as target:
            for name in source.namelist():
                payload = (
                    b"CONNECTOR_ID = 'tampered'\n" if name == "connector.py" else source.read(name)
                )
                target.writestr(name, payload)
        tamper_denied = False
        try:
            verify_signed_package(tampered, LAB_SIGNER)
        except ValueError:
            tamper_denied = True
        with zipfile.ZipFile(package) as archive:
            manifest = json.loads(archive.read("META-INF/manifest.json"))
            sbom = json.loads(archive.read("META-INF/sbom.cdx.json"))
        sbom_files = {
            component["name"]: component["hashes"][0]["content"] for component in sbom["components"]
        }
        sbom_complete = sbom_files == manifest["files"]
    checks.append(
        CertificationCheck(
            "package.signature-sbom-and-denial",
            signature_ok and wrong_key_denied and tamper_denied and sbom_complete,
            (
                f"signature={signature_ok}; wrong_key_denied={wrong_key_denied}; "
                f"tamper_denied={tamper_denied}; sbom={sbom_complete}"
            ),
        )
    )

    schemas_unchanged, schema_detail = _schema_reuse()
    leakage_count, leakage_detail = _core_leakage()
    scenarios = excursion_count()
    checks.extend(
        (
            CertificationCheck(
                "contracts.phase2-compatible-evolution", schemas_unchanged, schema_detail
            ),
            CertificationCheck(
                "portability.no-first-pilot-core-tokens",
                leakage_count == 0,
                f"findings={leakage_detail}",
            ),
            CertificationCheck(
                "scenario.temperature-excursions", scenarios >= 1, f"excursions={scenarios}"
            ),
        )
    )
    metrics = (
        _metric(
            definitions, "M1", float(deterministic and fixtures_match), "two equal generations"
        ),
        _metric(definitions, "M2", float(references_valid), "all references resolved"),
        _metric(definitions, "M3", float(operation_coverage), "3/3 OpenAPI operations"),
        _metric(definitions, "M4", float(source_compiles), "generated Python compiled"),
        _metric(definitions, "M5", float(signature_ok), "offline signature verified"),
        _metric(definitions, "M6", float(sbom_complete), "all payload files represented"),
        _metric(
            definitions,
            "M7",
            float(wrong_key_denied and tamper_denied),
            "wrong signer and tampered payload rejected",
        ),
        _metric(definitions, "M8", float(schemas_unchanged), schema_detail),
        _metric(definitions, "M9", float(leakage_count), leakage_detail),
        _metric(definitions, "M10", float(scenarios >= 1), f"excursions={scenarios}"),
    )
    checks.append(
        CertificationCheck(
            "gqm.phase3-plan-complete",
            {item["metricId"] for item in plan["metrics"]} == {item.metric_id for item in metrics},
            f"goals={len(plan['goals'])}; metrics={len(metrics)}",
        )
    )
    return Phase3Report(
        "phase-3",
        "cold-chain-excursion-response-lab",
        all(check.passed for check in checks) and all(metric.passed for metric in metrics),
        tuple(checks),
        metrics,
        (
            "Certifies a synthetic second-industry pack, deterministic scaffolding and offline "
            "artifact integrity. It does not establish production carrier connectivity, "
            "deployment/runtime proof, asymmetric publisher identity or stakeholder acceptance."
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cold-chain-phase3-certify")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = certify_phase3()
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
