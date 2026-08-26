from data_source_harness.contracts import run_phase0_gate, validate_contract_fixtures


def test_all_contract_fixtures_exercise_acceptance_and_rejection() -> None:
    checks = validate_contract_fixtures()
    assert checks
    assert all(check.passed for check in checks), checks


def test_phase0_artifact_gate_passes() -> None:
    report = run_phase0_gate()
    assert report.passed, report
