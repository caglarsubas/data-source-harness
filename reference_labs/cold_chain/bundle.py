"""Build and verify the deterministic disconnected Phase-3 lab bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

from data_source_harness import __version__ as harness_version
from data_source_harness.packaging import (
    FIXED_ZIP_TIME,
    build_signed_package,
    verify_signed_package,
)

from .certify import LAB_SIGNER
from .lab import LAB_ROOT, REPOSITORY_ROOT, carrier_scaffold

DEFAULT_OUTPUT = REPOSITORY_ROOT / "dist/cold-chain-reference-lab-1.0.0.zip"
DEFAULT_CONNECTOR = REPOSITORY_ROOT / "dist/coldchain-carrier-api-0.1.0.zip"


def build_connector(path: Path = DEFAULT_CONNECTOR) -> str:
    scaffold = carrier_scaffold()
    return build_signed_package(
        path,
        scaffold.files,
        LAB_SIGNER,
        component_name=scaffold.connector_id,
        component_version="0.1.0",
    )


def _inputs(connector: Path, wheel: Path) -> tuple[tuple[str, Path], ...]:
    candidates: list[tuple[str, Path]] = []
    roots = (
        ("reference_labs/cold_chain", LAB_ROOT),
        ("schemas/v1", REPOSITORY_ROOT / "schemas/v1"),
        ("compatibility", REPOSITORY_ROOT / "compatibility"),
        ("deployment/profiles", REPOSITORY_ROOT / "deployment/profiles"),
        ("docs/architecture", REPOSITORY_ROOT / "docs/architecture"),
        ("docs/testing", REPOSITORY_ROOT / "docs/testing"),
    )
    for archive_root, source_root in roots:
        for path in source_root.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                candidates.append(
                    (f"{archive_root}/{path.relative_to(source_root).as_posix()}", path)
                )
    candidates.extend(
        (
            (f"connectors/{connector.name}", connector),
            (f"wheels/{wheel.name}", wheel),
        )
    )
    return tuple(sorted(candidates))


def build_bundle(output: Path = DEFAULT_OUTPUT) -> str:
    wheel = REPOSITORY_ROOT / (
        f"dist/orchestra_data_source_harness-{harness_version}-py3-none-any.whl"
    )
    if not wheel.is_file():
        raise RuntimeError(f"build the core harness wheel before creating the lab bundle: {wheel}")
    build_connector()
    entries = _inputs(DEFAULT_CONNECTOR, wheel)
    manifest = {
        "schemaVersion": "coldchain.lab.bundle/v1",
        "files": {
            archive_path: hashlib.sha256(source.read_bytes()).hexdigest()
            for archive_path, source in entries
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for archive_path, source in entries:
            info = zipfile.ZipInfo(archive_path, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, source.read_bytes())
        info = zipfile.ZipInfo("bundle-manifest.json", FIXED_ZIP_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        bundle.writestr(info, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return hashlib.sha256(output.read_bytes()).hexdigest()


def verify_bundle(path: Path = DEFAULT_OUTPUT) -> str:
    with zipfile.ZipFile(path) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)) or "bundle-manifest.json" not in names:
            raise ValueError("bundle has duplicate entries or no manifest")
        manifest = json.loads(bundle.read("bundle-manifest.json"))
        for archive_path, expected in manifest["files"].items():
            if hashlib.sha256(bundle.read(archive_path)).hexdigest() != expected:
                raise ValueError(f"bundle checksum mismatch: {archive_path}")
        connector_entry = f"connectors/{DEFAULT_CONNECTOR.name}"
        with tempfile.TemporaryDirectory() as directory:
            connector = Path(directory) / DEFAULT_CONNECTOR.name
            connector.write_bytes(bundle.read(connector_entry))
            verify_signed_package(connector, LAB_SIGNER)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cold-chain-lab-bundle")
    parser.add_argument("operation", choices=("build", "verify"))
    parser.add_argument("--path", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    digest = build_bundle(args.path) if args.operation == "build" else verify_bundle(args.path)
    print(json.dumps({"path": str(args.path), "sha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
