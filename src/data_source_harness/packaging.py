"""Offline-verifiable connector packages with checksums, SBOM and pluggable signing."""

from __future__ import annotations

import hashlib
import hmac
import json
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class ArchiveLimits:
    max_entries: int = 10_000
    max_entry_bytes: int = 256 * 1024 * 1024
    max_total_bytes: int = 1024 * 1024 * 1024
    max_compression_ratio: float = 1_000.0

    def __post_init__(self) -> None:
        if (
            min(
                self.max_entries,
                self.max_entry_bytes,
                self.max_total_bytes,
                self.max_compression_ratio,
            )
            <= 0
        ):
            raise ValueError("archive verification limits must be positive")


class ArtifactSigner(Protocol):
    key_id: str
    algorithm: str

    def sign(self, payload: bytes) -> str: ...

    def verify(self, payload: bytes, signature: str) -> bool: ...


@dataclass(frozen=True)
class HmacSha256Signer:
    """Offline lab signer; production publishers should inject an asymmetric/HSM signer."""

    key_id: str
    secret: bytes
    algorithm: str = "HMAC-SHA256"

    def __post_init__(self) -> None:
        if not self.key_id or len(self.secret) < 16:
            raise ValueError("key id and at least 128 bits of lab key material are required")

    def sign(self, payload: bytes) -> str:
        return hmac.new(self.secret, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(payload), signature)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def build_signed_package(
    output: Path,
    files: Mapping[str, bytes],
    signer: ArtifactSigner,
    *,
    component_name: str,
    component_version: str,
    dependencies: Mapping[str, str] | None = None,
) -> str:
    if not files or any(path.startswith("/") or ".." in Path(path).parts for path in files):
        raise ValueError("package paths must be non-empty and relative")
    manifest = {
        "schemaVersion": "data.harness.package/v1",
        "component": {"name": component_name, "version": component_version},
        "files": {
            path: hashlib.sha256(payload).hexdigest() for path, payload in sorted(files.items())
        },
    }
    dependency_components = [
        {
            "type": "library",
            "name": name,
            "version": version,
            "bom-ref": f"pkg:pypi/{name}@{version}",
            "purl": f"pkg:pypi/{name}@{version}",
        }
        for name, version in sorted((dependencies or {}).items())
    ]
    application_ref = f"pkg:generic/{component_name}@{component_version}"
    file_components = [
        {
            "type": "file",
            "name": path,
            "bom-ref": f"file:{path}",
            "hashes": [{"alg": "SHA-256", "content": digest}],
        }
        for path, digest in manifest["files"].items()
    ]
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": component_name,
                "version": component_version,
                "bom-ref": application_ref,
            }
        },
        "components": file_components + dependency_components,
        "dependencies": [
            {
                "ref": application_ref,
                "dependsOn": [
                    component["bom-ref"] for component in file_components + dependency_components
                ],
            },
            *[
                {"ref": component["bom-ref"], "dependsOn": []}
                for component in file_components + dependency_components
            ],
        ],
    }
    signed_payload = _canonical(manifest) + b"\n" + _canonical(sbom)
    signature = {
        "schemaVersion": "data.harness.signature/v1",
        "algorithm": signer.algorithm,
        "keyId": signer.key_id,
        "value": signer.sign(signed_payload),
    }
    entries = dict(files)
    entries["META-INF/manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode()
    entries["META-INF/sbom.cdx.json"] = (json.dumps(sbom, indent=2, sort_keys=True) + "\n").encode()
    entries["META-INF/signature.json"] = (
        json.dumps(signature, indent=2, sort_keys=True) + "\n"
    ).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, payload in sorted(entries.items()):
            info = zipfile.ZipInfo(path, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, payload)
    return hashlib.sha256(output.read_bytes()).hexdigest()


def verify_signed_package(
    path: Path,
    signer: ArtifactSigner,
    limits: ArchiveLimits | None = None,
) -> str:
    limits = limits or ArchiveLimits()
    with zipfile.ZipFile(path) as archive:
        information = archive.infolist()
        names = [item.filename for item in information]
        if len(names) != len(set(names)):
            raise ValueError("package contains duplicate paths")
        if len(information) > limits.max_entries:
            raise ValueError("package contains too many entries")
        total_size = 0
        for item in information:
            total_size += item.file_size
            if item.file_size > limits.max_entry_bytes or total_size > limits.max_total_bytes:
                raise ValueError("package exceeds uncompressed size limits")
            if item.file_size and item.compress_size == 0:
                raise ValueError("package entry has an invalid compression size")
            if (
                item.compress_size
                and item.file_size / item.compress_size > limits.max_compression_ratio
            ):
                raise ValueError("package entry exceeds compression ratio limit")
        manifest = json.loads(archive.read("META-INF/manifest.json"))
        sbom = json.loads(archive.read("META-INF/sbom.cdx.json"))
        signature = json.loads(archive.read("META-INF/signature.json"))
        expected_names = set(manifest["files"]) | {
            "META-INF/manifest.json",
            "META-INF/sbom.cdx.json",
            "META-INF/signature.json",
        }
        if set(names) != expected_names:
            raise ValueError("package contains unsigned or missing paths")
        if signature["algorithm"] != signer.algorithm or signature["keyId"] != signer.key_id:
            raise ValueError("package signer identity does not match")
        for entry, expected in manifest["files"].items():
            if hashlib.sha256(archive.read(entry)).hexdigest() != expected:
                raise ValueError(f"package checksum mismatch: {entry}")
        sbom_files = {
            component["name"]: next(
                item["content"] for item in component["hashes"] if item["alg"] == "SHA-256"
            )
            for component in sbom["components"]
            if component.get("type") == "file"
        }
        if sbom_files != manifest["files"]:
            raise ValueError("SBOM does not cover every payload file")
        if (
            sbom.get("bomFormat") != "CycloneDX"
            or not sbom.get("dependencies")
            or not all(component.get("bom-ref") for component in sbom["components"])
        ):
            raise ValueError("SBOM component/dependency graph is incomplete")
        payload = _canonical(manifest) + b"\n" + _canonical(sbom)
        if not signer.verify(payload, signature["value"]):
            raise ValueError("package signature verification failed")
    return hashlib.sha256(path.read_bytes()).hexdigest()
