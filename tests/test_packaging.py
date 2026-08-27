from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from data_source_harness.packaging import (
    HmacSha256Signer,
    build_signed_package,
    verify_signed_package,
)


def _signer() -> HmacSha256Signer:
    return HmacSha256Signer("phase3-lab-key", b"phase3-reference-key-material")


def test_package_is_deterministic_signed_and_sbom_covered(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    files = {"connector.py": b"VALUE = 1\n", "profile.json": b"{}\n"}
    digest = build_signed_package(
        first, files, _signer(), component_name="test", component_version="1"
    )
    assert digest == build_signed_package(
        second, files, _signer(), component_name="test", component_version="1"
    )
    assert verify_signed_package(first, _signer()) == digest
    with pytest.raises(ValueError, match="signer identity"):
        verify_signed_package(first, HmacSha256Signer("other", b"other-reference-key-material"))


def test_tampered_payload_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "package.zip"
    tampered = tmp_path / "tampered.zip"
    build_signed_package(
        package,
        {"connector.py": b"VALUE = 1\n"},
        _signer(),
        component_name="test",
        component_version="1",
    )
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(tampered, "w") as target:
        for name in source.namelist():
            payload = b"VALUE = 2\n" if name == "connector.py" else source.read(name)
            target.writestr(name, payload)
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_signed_package(tampered, _signer())
