from __future__ import annotations

import hashlib
from pathlib import Path

from reference_labs.cold_chain.bundle import build_bundle, verify_bundle
from reference_labs.cold_chain.certify import certify_phase3
from reference_labs.cold_chain.lab import excursion_count, generated_data


def test_phase3_certificate_passes() -> None:
    report = certify_phase3()
    assert report.passed
    assert len(report.metrics) == 10
    assert all(item.passed for item in report.checks)


def test_cold_chain_scenario_has_grounded_excursions() -> None:
    data = generated_data()
    assert len(data["shipments"]) == 4
    assert len(data["sensor-readings"]) == 12
    assert excursion_count() >= 1


def test_disconnected_bundle_is_deterministic_and_verifiable(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    wheel = repository_root / "dist/orchestra_data_source_harness-0.4.0-py3-none-any.whl"
    if not wheel.exists():
        return
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    first_digest = build_bundle(first)
    second_digest = build_bundle(second)
    assert first_digest == second_digest
    assert verify_bundle(first) == hashlib.sha256(first.read_bytes()).hexdigest()
