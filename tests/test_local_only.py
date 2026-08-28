from pathlib import Path

from data_source_harness.local_only import audit_local_only_automation


def test_repository_automation_has_no_cloud_or_cluster_provisioning() -> None:
    root = Path(__file__).resolve().parents[1]
    assert audit_local_only_automation(root) == ()


def test_guard_reports_prohibited_automation(tmp_path: Path) -> None:
    workflow = tmp_path / ".github/workflows"
    workflow.mkdir(parents=True)
    (workflow / "deploy.yml").write_text("run: gcloud run deploy service\n", encoding="utf-8")
    assert audit_local_only_automation(tmp_path) == (".github/workflows/deploy.yml:gcp-cli",)


def test_guard_rejects_remote_container_context(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "run.sh").write_text("docker context use remote-cluster\n", encoding="utf-8")
    assert audit_local_only_automation(tmp_path) == ("scripts/run.sh:remote-container-engine",)
