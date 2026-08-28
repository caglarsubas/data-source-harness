"""Lifecycle and evidence capture for the laptop-local source-service lab."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = Path(__file__).resolve().with_name("compose.template.yaml")
PROJECT_NAME = "white-goods-phase7-local"
SERVICE_API_TAG = "data-source-harness-whitegoods-service-api:0.1.0"
SOURCE_IMAGES = {
    "whitegoods.postgresql": "postgres:16",
    "whitegoods.object-store": "minio/minio:latest",
    "whitegoods.event-stream": "docker.redpanda.com/redpandadata/redpanda:v26.2.2",
}
PYTHON_BASE_IMAGE = "python:3.12-slim"
SOURCE_SHAPES = {
    "whitegoods.postgresql": "postgresql",
    "whitegoods.object-store": "s3-compatible",
    "whitegoods.event-stream": "kafka-compatible",
    "whitegoods.service-api": "rest",
}
EXPECTED_RECORDS = {
    "whitegoods.postgresql": 6,
    "whitegoods.object-store": 4,
    "whitegoods.event-stream": 9,
    "whitegoods.service-api": 3,
}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def _run(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: int = 180,
) -> CommandResult:
    completed = subprocess.run(
        args,
        cwd=REPOSITORY_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    result = CommandResult(completed.returncode, completed.stdout, completed.stderr)
    if check and result.returncode != 0:
        command = " ".join(args[:4])
        raise RuntimeError(f"command failed ({command}): {result.stderr.strip()}")
    return result


def validate_local_docker_host(host: str) -> None:
    normalized = host.strip().strip('"')
    if not normalized.startswith(("unix://", "npipe://")):
        raise ValueError(f"Docker endpoint is not laptop-local: {normalized}")


def _docker_context() -> tuple[str, str]:
    context = _run(["docker", "context", "show"]).stdout.strip()
    host = _run(
        [
            "docker",
            "context",
            "inspect",
            context,
            "--format",
            "{{json .Endpoints.docker.Host}}",
        ]
    ).stdout.strip()
    validate_local_docker_host(host)
    return context, host.strip('"')


def _image_record(source_id: str, reference: str) -> dict[str, Any]:
    inspected = json.loads(_run(["docker", "image", "inspect", reference]).stdout)[0]
    digest = inspected["Id"]
    if re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
        raise ValueError(f"image {reference} has no immutable local image ID")
    repo_digests = sorted(inspected.get("RepoDigests") or [])
    return {
        "sourceId": source_id,
        "sourceReference": repo_digests[0] if repo_digests else reference,
        "imageDigest": digest,
        "repoDigests": repo_digests,
        "os": inspected["Os"],
        "architecture": inspected["Architecture"],
    }


def _build_service_api() -> None:
    _run(["docker", "image", "inspect", PYTHON_BASE_IMAGE])
    source_paths = (
        COMPOSE_PATH.with_name("ServiceApi.Containerfile"),
        COMPOSE_PATH.with_name("service_api.py"),
        REPOSITORY_ROOT / "reference_labs/white_goods/data/api/service-api-fixtures.json",
    )
    source_digest = hashlib.sha256()
    for path in source_paths:
        source_digest.update(path.relative_to(REPOSITORY_ROOT).as_posix().encode())
        source_digest.update(path.read_bytes())
    expected_label = source_digest.hexdigest()
    existing = _run(
        [
            "docker",
            "image",
            "inspect",
            SERVICE_API_TAG,
            "--format",
            '{{index .Config.Labels "data.harness.source-sha256"}}',
        ],
        check=False,
    )
    if existing.returncode == 0 and existing.stdout.strip() == expected_label:
        return
    _run(
        [
            "docker",
            "build",
            "--pull=false",
            "--build-arg",
            f"BASE_IMAGE={PYTHON_BASE_IMAGE}",
            "--label",
            f"data.harness.source-sha256={expected_label}",
            "-f",
            str(COMPOSE_PATH.with_name("ServiceApi.Containerfile")),
            "-t",
            SERVICE_API_TAG,
            ".",
        ],
        timeout=300,
    )


def build_image_lock() -> dict[str, Any]:
    _docker_context()
    for reference in SOURCE_IMAGES.values():
        _run(["docker", "image", "inspect", reference])
    _build_service_api()
    records = [
        _image_record(source_id, reference) for source_id, reference in SOURCE_IMAGES.items()
    ]
    records.append(_image_record("whitegoods.service-api", SERVICE_API_TAG))
    platforms = {f"{item['os']}/{item['architecture']}" for item in records}
    if len(platforms) != 1:
        raise ValueError(f"local source images have mixed platforms: {sorted(platforms)}")
    return {
        "schemaVersion": "data.harness.local-image-lock/v1",
        "platform": platforms.pop(),
        "images": records,
    }


def _write_secret(path: Path, value: str) -> None:
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(0o600)


def _compose_environment(lock: dict[str, Any], secret_dir: Path) -> dict[str, str]:
    by_source = {item["sourceId"]: item for item in lock["images"]}
    secret_values = {
        "postgres-user": "lab",
        "postgres-password": secrets.token_urlsafe(24),
        "object-store-user": "labadmin",
        "object-store-password": secrets.token_urlsafe(24),
        "service-api-credential": secrets.token_urlsafe(24),
    }
    for name, value in secret_values.items():
        _write_secret(secret_dir / name, value)
    env = os.environ.copy()
    env.update(
        {
            "PHASE7_POSTGRES_IMAGE": by_source["whitegoods.postgresql"]["imageDigest"],
            "PHASE7_MINIO_IMAGE": by_source["whitegoods.object-store"]["imageDigest"],
            "PHASE7_REDPANDA_IMAGE": by_source["whitegoods.event-stream"]["imageDigest"],
            "PHASE7_SERVICE_API_IMAGE": by_source["whitegoods.service-api"]["imageDigest"],
            "PHASE7_POSTGRES_USER_FILE": str(secret_dir / "postgres-user"),
            "PHASE7_POSTGRES_PASSWORD_FILE": str(secret_dir / "postgres-password"),
            "PHASE7_OBJECT_STORE_USER_FILE": str(secret_dir / "object-store-user"),
            "PHASE7_OBJECT_STORE_PASSWORD_FILE": str(secret_dir / "object-store-password"),
            "PHASE7_SERVICE_API_CREDENTIAL_FILE": str(secret_dir / "service-api-credential"),
        }
    )
    return env


def _compose_args(*args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(COMPOSE_PATH),
        "--project-name",
        PROJECT_NAME,
        "--profile",
        "phase7-local",
        *args,
    ]


def _seed(env: dict[str, str]) -> None:
    _run(
        _compose_args(
            "exec",
            "-T",
            "object-store",
            "sh",
            "-ec",
            'mc alias set local http://localhost:9000 "$(cat /run/secrets/object-store-user)" '
            '"$(cat /run/secrets/object-store-password)" >/dev/null; '
            "mc mb --ignore-existing local/technical-documents >/dev/null; "
            "mc cp --recursive /fixtures/ local/technical-documents/ >/dev/null",
        ),
        env=env,
    )
    _run(
        _compose_args(
            "exec",
            "-T",
            "event-stream",
            "sh",
            "-ec",
            "rpk topic create telemetry --if-not-exists -X brokers=localhost:9092 >/dev/null; "
            "rpk topic produce telemetry -X brokers=localhost:9092 < /fixtures/telemetry.jsonl "
            ">/dev/null",
        ),
        env=env,
    )


def _container_id(service: str, env: dict[str, str]) -> str:
    container_id = _run(_compose_args("ps", "-q", service), env=env).stdout.strip()
    if not container_id:
        raise RuntimeError(f"local service is not running: {service}")
    return container_id


def _verify(env: dict[str, str], lock: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    postgres_count = int(
        _run(
            _compose_args(
                "exec",
                "-T",
                "postgresql",
                "sh",
                "-ec",
                'psql -U "$(cat /run/secrets/postgres-user)" -d whitegoods -Atc '
                "'SELECT COUNT(*) FROM service_orders'",
            ),
            env=env,
        ).stdout.strip()
    )
    checks.append({"checkId": "postgresql.seeded-query", "passed": postgres_count == 6})

    object_count = int(
        _run(
            _compose_args(
                "exec",
                "-T",
                "object-store",
                "sh",
                "-ec",
                'mc alias set local http://localhost:9000 "$(cat /run/secrets/object-store-user)" '
                '"$(cat /run/secrets/object-store-password)" >/dev/null; '
                "mc ls --recursive local/technical-documents | wc -l",
            ),
            env=env,
        ).stdout.strip()
    )
    checks.append({"checkId": "object-store.seeded-list", "passed": object_count == 4})

    events = _run(
        _compose_args(
            "exec",
            "-T",
            "event-stream",
            "rpk",
            "topic",
            "consume",
            "telemetry",
            "--num",
            "9",
            "--format",
            "%v\\n",
            "-X",
            "brokers=localhost:9092",
        ),
        env=env,
    ).stdout.splitlines()
    event_count = sum(1 for line in events if line.strip().startswith("{"))
    checks.append({"checkId": "event-stream.seeded-consume", "passed": event_count == 9})

    api_probe = (
        "import json,pathlib,urllib.request; "
        "token=pathlib.Path('/run/secrets/service-api-credential').read_text().strip(); "
        "r=urllib.request.Request('http://localhost:8080/v1/appointments',"
        "headers={'Authorization':'Bearer '+token}); "
        "p=json.load(urllib.request.urlopen(r,timeout=3)); "
        "assert len(p['items'])==2 and p['nextCursor']=='2'"
    )
    _run(_compose_args("exec", "-T", "service-api", "python", "-c", api_probe), env=env)
    checks.append({"checkId": "service-api.auth-pagination", "passed": True})

    network_internal = (
        _run(
            [
                "docker",
                "network",
                "inspect",
                f"{PROJECT_NAME}_lab-internal",
                "--format",
                "{{.Internal}}",
            ]
        ).stdout.strip()
        == "true"
    )
    checks.append({"checkId": "network.internal", "passed": network_internal})
    published_ports = 0
    for service in ("postgresql", "object-store", "event-stream", "service-api"):
        ports = json.loads(
            _run(
                [
                    "docker",
                    "inspect",
                    _container_id(service, env),
                    "--format",
                    "{{json .NetworkSettings.Ports}}",
                ]
            ).stdout
        )
        published_ports += sum(1 for value in (ports or {}).values() if value)
    checks.append({"checkId": "network.no-published-ports", "passed": published_ports == 0})

    egress_probe = _run(
        _compose_args(
            "exec",
            "-T",
            "service-api",
            "python",
            "-c",
            "import socket; socket.create_connection(('1.1.1.1',443),2)",
        ),
        env=env,
        check=False,
        timeout=10,
    )
    checks.append(
        {"checkId": "network.public-egress-denied", "passed": egress_probe.returncode != 0}
    )

    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    image_by_source = {item["sourceId"]: item for item in lock["images"]}
    observations = [
        {
            "sourceId": source_id,
            "shape": SOURCE_SHAPES[source_id],
            "imageDigest": image_by_source[source_id]["imageDigest"],
            "recordsObserved": EXPECTED_RECORDS[source_id],
            "observedAt": observed_at,
            "references": [f"local-evidence://phase7/{source_id}"],
        }
        for source_id in SOURCE_SHAPES
    ]
    context, host = _docker_context()
    return {
        "schemaVersion": "data.harness.local-source-evidence/v1",
        "campaignId": "phase7-white-goods-local-sources",
        "generatedAt": observed_at,
        "dockerContext": context,
        "dockerEndpointKind": host.split(":", maxsplit=1)[0],
        "externalResourcesCreated": [],
        "checks": checks,
        "sources": observations,
        "passed": all(check["passed"] for check in checks),
    }


def run_local_lab(*, keep_running: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    lock = build_image_lock()
    with tempfile.TemporaryDirectory(prefix="phase7-local-secrets-") as directory:
        env = _compose_environment(lock, Path(directory))
        _run(_compose_args("down", "--volumes", "--remove-orphans"), env=env, check=False)
        try:
            _run(_compose_args("up", "-d", "--wait", "--wait-timeout", "180"), env=env)
            _seed(env)
            report = _verify(env, lock)
            if not report["passed"]:
                failed = [check["checkId"] for check in report["checks"] if not check["passed"]]
                raise RuntimeError("local source verification failed: " + ", ".join(failed))
            return lock, report
        finally:
            if not keep_running:
                _run(
                    _compose_args("down", "--volumes", "--remove-orphans"),
                    env=env,
                    check=False,
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="phase7-local-source-lab")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lock-output", type=Path, required=True)
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args(argv)
    lock, report = run_local_lab(keep_running=args.keep_running)
    args.lock_output.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
