"""Build and certify the digest-bound local harness acceptance image."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_source_harness import __version__
from reference_labs.white_goods.live import local_lab

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LIVE_ROOT = Path(__file__).resolve().parent
REQUIREMENTS_PATH = LIVE_ROOT / "harness-requirements.txt"
CONTAINERFILE_PATH = LIVE_ROOT / "HarnessAcceptance.Containerfile"
WHEELHOUSE_ROOT = REPOSITORY_ROOT / "dist/live-wheelhouse"
WHEELHOUSE_LOCK_PATH = REPOSITORY_ROOT / "compatibility/phase7-live-wheelhouse.lock.json"
IMAGE_TAG = f"data-source-harness-phase7-acceptance:{__version__}"
PYTHON_BASE_IMAGE = "python:3.12-slim"
TARGET_PLATFORM = "manylinux_2_17_aarch64"


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _source_revision() -> str:
    dirty = local_lab._run(["git", "status", "--porcelain", "--untracked-files=no"]).stdout.strip()
    if dirty:
        raise RuntimeError("commit tracked source changes before building revision-bound evidence")
    return local_lab._run(["git", "rev-parse", "HEAD"]).stdout.strip()


def _prepare_wheelhouse() -> dict[str, Any]:
    WHEELHOUSE_ROOT.mkdir(parents=True, exist_ok=True)
    for path in WHEELHOUSE_ROOT.iterdir():
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--dest",
            str(WHEELHOUSE_ROOT),
            "--only-binary=:all:",
            "--platform",
            TARGET_PLATFORM,
            "--implementation",
            "cp",
            "--python-version",
            "312",
            "-r",
            str(REQUIREMENTS_PATH),
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
    )
    files = {path.name: _sha256(path) for path in sorted(WHEELHOUSE_ROOT.glob("*.whl"))}
    lock = {
        "schemaVersion": "data.harness.live-wheelhouse-lock/v1",
        "requirementsDigest": _sha256(REQUIREMENTS_PATH),
        "target": {"platform": "linux/arm64", "pythonVersion": "3.12"},
        "files": files,
    }
    WHEELHOUSE_LOCK_PATH.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return lock


def _build_harness_image(revision: str) -> dict[str, Any]:
    base = json.loads(local_lab._run(["docker", "image", "inspect", PYTHON_BASE_IMAGE]).stdout)[0]
    if base["Os"] != "linux" or base["Architecture"] != "arm64":
        raise RuntimeError("the preloaded Python base image is not linux/arm64")
    subprocess.run(("uv", "build"), cwd=REPOSITORY_ROOT, check=True)
    local_lab._run(
        [
            "docker",
            "build",
            "--pull=false",
            "--build-arg",
            f"BASE_IMAGE={PYTHON_BASE_IMAGE}",
            "--build-arg",
            f"HARNESS_VERSION={__version__}",
            "--build-arg",
            f"HARNESS_SOURCE_REVISION={revision}",
            "--label",
            f"data.harness.base-image-digest={base['Id']}",
            "-f",
            str(CONTAINERFILE_PATH),
            "-t",
            IMAGE_TAG,
            ".",
        ],
        timeout=600,
    )
    image = json.loads(local_lab._run(["docker", "image", "inspect", IMAGE_TAG]).stdout)[0]
    labels = image["Config"]["Labels"]
    if labels.get("data.harness.source-revision") != revision:
        raise RuntimeError("built image is not bound to the requested source revision")
    if labels.get("data.harness.base-image-digest") != base["Id"]:
        raise RuntimeError("built image is not bound to the inspected local base image")
    return {
        "artifactDigest": image["Id"],
        "baseImageDigest": base["Id"],
        "os": image["Os"],
        "architecture": image["Architecture"],
    }


def run_harness_runtime_lab() -> dict[str, Any]:
    local_lab._docker_context()
    revision = _source_revision()
    wheelhouse = _prepare_wheelhouse()
    harness_image = _build_harness_image(revision)
    source_lock = local_lab.build_image_lock()
    env = local_lab._compose_environment(source_lock)
    env.update(
        {
            "PHASE7_HARNESS_IMAGE": harness_image["artifactDigest"],
            "PHASE7_HARNESS_SOURCE_REVISION": revision,
            "PHASE7_HARNESS_VERSION": __version__,
        }
    )
    local_lab._run(
        local_lab._compose_args("down", "--volumes", "--remove-orphans"), env=env, check=False
    )
    try:
        local_lab._run(
            local_lab._compose_args("up", "-d", "--wait", "--wait-timeout", "180"),
            env=env,
        )
        local_lab._seed(env)
        probe = local_lab._run(
            local_lab._compose_args(
                "--profile",
                "phase7-harness",
                "run",
                "--rm",
                "--no-deps",
                "harness-acceptance",
            ),
            env=env,
            timeout=240,
        )
        report = json.loads(probe.stdout)
        network_internal = (
            local_lab._run(
                [
                    "docker",
                    "network",
                    "inspect",
                    f"{local_lab.PROJECT_NAME}_lab-internal",
                    "--format",
                    "{{.Internal}}",
                ]
            ).stdout.strip()
            == "true"
        )
        report["checks"].extend(
            (
                {
                    "checkId": "artifact.local-image-loaded",
                    "passed": bool(harness_image["artifactDigest"]),
                    "observed": 1,
                },
                {
                    "checkId": "artifact.offline-wheelhouse-bound",
                    "passed": len(wheelhouse["files"]) >= 15,
                    "observed": len(wheelhouse["files"]),
                },
                {
                    "checkId": "runtime.internal-network-only",
                    "passed": network_internal,
                    "observed": 1 if network_internal else 0,
                },
            )
        )
        report["baseImageDigest"] = harness_image["baseImageDigest"]
        report["wheelhouseDigest"] = wheelhouse["requirementsDigest"]
        report["generatedAt"] = datetime.now(UTC).replace(microsecond=0).isoformat()
        report["passed"] = all(check["passed"] for check in report["checks"])
        if not report["passed"]:
            failed = [check["checkId"] for check in report["checks"] if not check["passed"]]
            raise RuntimeError("local harness runtime verification failed: " + ", ".join(failed))
        return report
    finally:
        local_lab._run(
            local_lab._compose_args("down", "--volumes", "--remove-orphans"),
            env=env,
            check=False,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="phase7-local-harness-runtime-lab")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_harness_runtime_lab()
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
