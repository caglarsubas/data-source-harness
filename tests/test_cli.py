import json
from pathlib import Path

from data_source_harness.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_cli_validates_contracts_and_writes_phase0_report(tmp_path, capsys) -> None:
    assert main(["validate"]) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["passed"] is True
    output = tmp_path / "phase0.json"
    assert main(["phase0-gate", "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["passed"] is True and report["phase"] == "phase-0"
    assert json.loads(capsys.readouterr().out) == report


def test_cli_validates_partial_acceptance_without_promoting_it(capsys, tmp_path) -> None:
    campaign_path = ROOT / "compatibility/phase7-acceptance-readiness.json"
    assert main(["verify-acceptance", "--input", str(campaign_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["structurallyValid"] is True
    assert result["accepted"] is False
    assert result["passed"] is True

    assert (
        main(
            [
                "verify-acceptance",
                "--input",
                str(campaign_path),
                "--require-accepted",
            ]
        )
        == 1
    )
    required = json.loads(capsys.readouterr().out)
    assert required["structurallyValid"] is True and required["passed"] is False

    forged = json.loads(campaign_path.read_text(encoding="utf-8"))
    forged["accepted"] = True
    forged["blockers"] = []
    forged_path = tmp_path / "forged.json"
    forged_path.write_text(json.dumps(forged), encoding="utf-8")
    assert main(["verify-acceptance", "--input", str(forged_path)]) == 1
    assert json.loads(capsys.readouterr().out)["structurallyValid"] is False
