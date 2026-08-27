"""Build and verify a deterministic offline reference-lab bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections.abc import Sequence
from pathlib import Path

from data_source_harness import __version__ as harness_version

LAB_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = LAB_ROOT.parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "dist/white-goods-reference-lab-1.1.0.zip"
FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def _inputs(wheel: Path | None = None) -> tuple[tuple[str, Path], ...]:
    candidates: list[tuple[str, Path]] = []
    roots = (
        ("reference_labs/white_goods", LAB_ROOT),
        ("schemas/v1", REPOSITORY_ROOT / "schemas/v1"),
        ("compatibility", REPOSITORY_ROOT / "compatibility"),
        ("contracts", REPOSITORY_ROOT / "contracts"),
        ("deployment/profiles", REPOSITORY_ROOT / "deployment/profiles"),
        ("docs/architecture", REPOSITORY_ROOT / "docs/architecture"),
        ("docs/testing", REPOSITORY_ROOT / "docs/testing"),
    )
    for archive_root, source_root in roots:
        for path in source_root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            relative = path.relative_to(source_root).as_posix()
            candidates.append((f"{archive_root}/{relative}", path))
    wheel = wheel or (
        REPOSITORY_ROOT / f"dist/orchestra_data_source_harness-{harness_version}-py3-none-any.whl"
    )
    if not wheel.is_file():
        raise RuntimeError(f"build the core harness wheel before creating the lab bundle: {wheel}")
    candidates.append((f"wheels/{wheel.name}", wheel))
    return tuple(sorted(candidates))


def build_bundle(output: Path = DEFAULT_OUTPUT, wheel: Path | None = None) -> str:
    entries = _inputs(wheel)
    manifest = {
        "schemaVersion": "whitegoods.lab.bundle/v1",
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
        manifest_info = zipfile.ZipInfo("bundle-manifest.json", FIXED_ZIP_TIME)
        manifest_info.compress_type = zipfile.ZIP_DEFLATED
        manifest_info.external_attr = 0o644 << 16
        bundle.writestr(
            manifest_info,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
        )
    return hashlib.sha256(output.read_bytes()).hexdigest()


def verify_bundle(path: Path = DEFAULT_OUTPUT) -> str:
    with zipfile.ZipFile(path) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)) or "bundle-manifest.json" not in names:
            raise ValueError("bundle has duplicate entries or no manifest")
        manifest = json.loads(bundle.read("bundle-manifest.json"))
        for archive_path, expected in manifest["files"].items():
            actual = hashlib.sha256(bundle.read(archive_path)).hexdigest()
            if actual != expected:
                raise ValueError(f"bundle checksum mismatch: {archive_path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="white-goods-lab-bundle")
    parser.add_argument("operation", choices=("build", "verify"))
    parser.add_argument("--path", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    digest = build_bundle(args.path) if args.operation == "build" else verify_bundle(args.path)
    print(json.dumps({"path": str(args.path), "sha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
