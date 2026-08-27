import hashlib
import json

from reference_labs.white_goods import runtime_bundle


def test_wheelhouse_readiness_requires_target_and_checksum_manifest(tmp_path, monkeypatch) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    runtime = tmp_path / "runtime"
    wheelhouse.mkdir()
    runtime.mkdir()
    requirements = runtime / "wheelhouse-requirements.txt"
    requirements.write_text("jsonschema==4.26.0\n")
    names = [f"{prefix}fixture.whl" for prefix in runtime_bundle.REQUIRED_WHEEL_PREFIXES]
    for name in names:
        (wheelhouse / name).write_bytes(name.encode())
    manifest = {
        "schemaVersion": "data.harness.wheelhouse/v1",
        "target": {
            "platform": "manylinux_2_17_x86_64",
            "implementation": "cp",
            "pythonVersion": "311",
        },
        "requirementsSha256": hashlib.sha256(requirements.read_bytes()).hexdigest(),
        "files": {
            name: hashlib.sha256((wheelhouse / name).read_bytes()).hexdigest() for name in names
        },
    }
    (wheelhouse / "wheelhouse-manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(runtime_bundle, "WHEELHOUSE_ROOT", wheelhouse)
    monkeypatch.setattr(runtime_bundle, "RUNTIME_ROOT", runtime)
    assert runtime_bundle._wheelhouse_complete()
    (wheelhouse / names[0]).write_bytes(b"tampered")
    assert not runtime_bundle._wheelhouse_complete()
