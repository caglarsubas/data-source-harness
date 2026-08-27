"""Build a signed deterministic transfer packet and explicit readiness record."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from data_source_harness import __version__ as harness_version
from data_source_harness.packaging import (
    HmacSha256Signer,
    build_signed_package,
    verify_signed_package,
)

LAB_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = LAB_ROOT.parents[1]
RUNTIME_ROOT = LAB_ROOT / "runtime"
DEFAULT_OUTPUT = REPOSITORY_ROOT / f"dist/white-goods-runtime-transfer-{harness_version}.zip"
LAB_SIGNER = HmacSha256Signer("white-goods-runtime-lab", b"white-goods-runtime-lab-key-material")
WHEELHOUSE_ROOT = REPOSITORY_ROOT / "dist/wheelhouse"
REQUIRED_WHEEL_PREFIXES = (
    "attrs-",
    "jsonschema-",
    "jsonschema_specifications-",
    "referencing-",
    "rpds_py-",
    "typing_extensions-",
)


def _wheelhouse_complete() -> bool:
    manifest_path = WHEELHOUSE_ROOT / "wheelhouse-manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        target = manifest["target"]
        files = manifest["files"]
        requirements_digest = hashlib.sha256(
            (RUNTIME_ROOT / "wheelhouse-requirements.txt").read_bytes()
        ).hexdigest()
        if (
            manifest.get("schemaVersion") != "data.harness.wheelhouse/v1"
            or target.get("platform") != "manylinux_2_17_x86_64"
            or target.get("implementation") != "cp"
            or target.get("pythonVersion") not in {"311", "312"}
            or manifest.get("requirementsSha256") != requirements_digest
            or not isinstance(files, dict)
        ):
            return False
        wheels = {path.name: path for path in WHEELHOUSE_ROOT.glob("*.whl")}
        if set(files) != set(wheels):
            return False
        if any(
            not isinstance(digest, str)
            or hashlib.sha256(wheels[name].read_bytes()).hexdigest() != digest
            for name, digest in files.items()
        ):
            return False
        names = {name.lower() for name in wheels}
        return all(
            any(name.startswith(prefix) for name in names) for prefix in REQUIRED_WHEEL_PREFIXES
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _runtime_dependencies() -> dict[str, str]:
    requirements = RUNTIME_ROOT / "wheelhouse-requirements.txt"
    dependencies: dict[str, str] = {}
    for line in requirements.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        name, separator, pinned_version = entry.partition("==")
        if not separator or not name or not pinned_version:
            raise ValueError(f"runtime dependency must be exactly pinned: {entry}")
        dependencies[name] = pinned_version
    return dependencies


def _files(wheel: Path | None = None) -> dict[str, bytes]:
    wheel = wheel or (
        REPOSITORY_ROOT / f"dist/orchestra_data_source_harness-{harness_version}-py3-none-any.whl"
    )
    if not wheel.is_file():
        uv = shutil.which("uv")
        if uv is None:
            raise RuntimeError(f"build the core harness wheel before the runtime packet: {wheel}")
        subprocess.run(
            (uv, "build"),
            cwd=REPOSITORY_ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    if not wheel.is_file():
        raise RuntimeError(f"runtime packet wheel build did not produce: {wheel}")
    files: dict[str, bytes] = {f"wheels/{wheel.name}": wheel.read_bytes()}
    for dependency_wheel in sorted(WHEELHOUSE_ROOT.glob("*.whl")):
        files[f"wheels/{dependency_wheel.name}"] = dependency_wheel.read_bytes()
    wheelhouse_manifest = WHEELHOUSE_ROOT / "wheelhouse-manifest.json"
    if wheelhouse_manifest.is_file():
        files["wheels/wheelhouse-manifest.json"] = wheelhouse_manifest.read_bytes()
    roots = (
        ("runtime", RUNTIME_ROOT),
        ("schemas/v1", REPOSITORY_ROOT / "schemas/v1"),
        ("compatibility", REPOSITORY_ROOT / "compatibility"),
        ("deployment/profiles", REPOSITORY_ROOT / "deployment/profiles"),
    )
    for archive_root, source_root in roots:
        for path in sorted(source_root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                files[f"{archive_root}/{path.relative_to(source_root).as_posix()}"] = (
                    path.read_bytes()
                )
    return files


def build_runtime_bundle(path: Path = DEFAULT_OUTPUT) -> str:
    return build_signed_package(
        path,
        _files(),
        LAB_SIGNER,
        component_name="white-goods-runtime-transfer",
        component_version=harness_version,
        dependencies=_runtime_dependencies(),
    )


def verify_runtime_bundle(path: Path = DEFAULT_OUTPUT) -> str:
    return verify_signed_package(path, LAB_SIGNER)


def readiness(path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    digest = verify_runtime_bundle(path)
    image_lock = json.loads((LAB_ROOT / "airgap-images.lock.json").read_text())
    images_resolved = all(item["airgapDigest"] for item in image_lock["images"])
    wheelhouse_complete = _wheelhouse_complete()
    blockers = []
    if not wheelhouse_complete:
        blockers.append("wheelhouse-incomplete")
    if not images_resolved:
        blockers.append("image-digests-unresolved")
    blockers.extend(
        ("oc-mirror-not-run", "live-cluster-not-available", "stakeholder-acceptance-missing")
    )
    return {
        "schemaVersion": "data.harness/v1",
        "bundleDigest": f"sha256:{digest}",
        "artifactIntegrity": True,
        "wheelhouseComplete": wheelhouse_complete,
        "imageDigestsResolved": images_resolved,
        "mirrorVerified": False,
        "deployed": False,
        "zeroEgressRuntimeVerified": False,
        "stakeholderAccepted": False,
        "blockers": blockers,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="white-goods-runtime-bundle")
    parser.add_argument("operation", choices=("build", "verify", "readiness"))
    parser.add_argument("--path", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if args.operation == "build":
        result: Any = {"path": str(args.path), "sha256": build_runtime_bundle(args.path)}
    elif args.operation == "verify":
        result = {"path": str(args.path), "sha256": verify_runtime_bundle(args.path)}
    else:
        result = readiness(args.path)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
