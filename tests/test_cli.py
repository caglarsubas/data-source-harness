import json

from data_source_harness.cli import main


def test_cli_validates_contracts_and_writes_phase0_report(tmp_path, capsys) -> None:
    assert main(["validate"]) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["passed"] is True
    output = tmp_path / "phase0.json"
    assert main(["phase0-gate", "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["passed"] is True and report["phase"] == "phase-0"
    assert json.loads(capsys.readouterr().out) == report
