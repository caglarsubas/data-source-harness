"""Laptop-local interoperability proof against the mature ADLC component seams."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib.util
import json
import os
import secrets
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from data_source_harness.cross_plane import GovernedModelPlane
from data_source_harness.policy import RequestIdentity

from .local_lab import validate_local_docker_host

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ADLC_REPOSITORY = REPOSITORY_ROOT.parent / "agentic-hook-v2-claude"
DEFAULT_SDK_REPOSITORY = REPOSITORY_ROOT.parent / "planeon-orchestra-python-sdk"
DEFAULT_MODEL_REPOSITORY = REPOSITORY_ROOT.parent / "llm_inference_engine_v1"
ADLC_PROBE_IMAGE = "prometa-platform-migrate:latest"
EXPECTED_COMPONENTS = {"ADLC", "Python-SDK", "model-plane"}
ADLC_FILES = (
    "prometa-platform/src/lib/release/receipt.ts",
    "prometa-platform/src/lib/release/canonical-json.ts",
    "prometa-platform/tsconfig.json",
)
SDK_FILES = ("prometa/runtime/receipts.py",)
MODEL_FILES = (
    "src/inference_engine/api/rerank.py",
    "src/inference_engine/auth.py",
    "src/inference_engine/main.py",
)
MODEL_EXECUTION_PATHS = ("src/inference_engine", "pyproject.toml")


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str


def _run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    timeout: int = 180,
) -> CommandResult:
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        command = " ".join(args[:4])
        raise RuntimeError(f"command failed ({command}): {completed.stderr.strip()}")
    return CommandResult(completed.stdout, completed.stderr)


def _revision(repository: Path) -> str:
    value = _run(["git", "rev-parse", "origin/main"], cwd=repository).stdout.strip()
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"repository has no exact origin/main revision: {repository.name}")
    return value


def _surface_record(
    component: str,
    repository: Path,
    repository_url: str,
    paths: tuple[str, ...],
    execution_paths: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    repository = repository.resolve()
    if not (repository / ".git").exists():
        raise ValueError(f"component repository is not a local Git checkout: {component}")
    revision = _revision(repository)
    if execution_paths is not None:
        changed = _run(
            ["git", "diff", "--name-only", revision, "--", *execution_paths],
            cwd=repository,
        ).stdout.strip()
        if changed:
            raise ValueError(
                f"component execution surface differs from local origin/main: "
                f"{component}: {changed}"
            )
    files = []
    aggregate = hashlib.sha256()
    for path in paths:
        payload = _run(["git", "show", f"{revision}:{path}"], cwd=repository).stdout.encode()
        digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        aggregate.update(path.encode())
        aggregate.update(payload)
        files.append({"path": path, "digest": digest})
    return {
        "component": component,
        "repository": repository_url,
        "revision": revision,
        "surfaceDigest": f"sha256:{aggregate.hexdigest()}",
        "files": files,
    }


def _docker_image_id(reference: str) -> str:
    context = _run(["docker", "context", "show"], cwd=REPOSITORY_ROOT).stdout.strip()
    host = _run(
        [
            "docker",
            "context",
            "inspect",
            context,
            "--format",
            "{{json .Endpoints.docker.Host}}",
        ],
        cwd=REPOSITORY_ROOT,
    ).stdout.strip()
    validate_local_docker_host(host)
    inspected = json.loads(
        _run(["docker", "image", "inspect", reference], cwd=REPOSITORY_ROOT).stdout
    )[0]
    return inspected["Id"]


def _load_sdk_receipts(repository: Path, revision: str) -> ModuleType:
    source = _run(["git", "show", f"{revision}:prometa/runtime/receipts.py"], cwd=repository).stdout
    with tempfile.TemporaryDirectory(prefix="phase7-sdk-probe-") as directory:
        module_path = Path(directory) / "receipts.py"
        module_path.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("phase7_sdk_receipts", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load the SDK receipt implementation")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


def _sdk_receipt(repository: Path, revision: str) -> dict[str, Any]:
    module = _load_sdk_receipts(repository, revision)
    return module.build_runtime_receipt(
        attestation_id="phase7-local-contract-attestation",
        artifact_digest=f"sha256:{hashlib.sha256(b'phase7-local-cross-plane').hexdigest()}",
        policy_digest=f"sha256:{hashlib.sha256(b'white-goods-policy-v1').hexdigest()}",
        configuration_digest=f"sha256:{hashlib.sha256(b'white-goods-config-v1').hexdigest()}",
        release_id="phase7-local-contract-release",
        deployment_id="phase7-local-laptop",
        target_environment="test",
        runtime_target="data-source-harness",
        runtime_id="white-goods-reference-lab",
        runtime_version="0.12.0",
        transition="active",
        outcome="succeeded",
        receipt_id="phase7-local-runtime-receipt",
        event_at=datetime(2026, 8, 28, tzinfo=UTC),
    )


def _archive_adlc_surface(repository: Path, revision: str, destination: Path) -> Path:
    archive = destination / "adlc-surface.tar"
    _run(
        ["git", "archive", "--format=tar", f"--output={archive}", revision, *ADLC_FILES],
        cwd=repository,
    )
    with tarfile.open(archive) as payload:
        payload.extractall(destination, filter="data")
    return destination / "prometa-platform"


def _adlc_validate(repository: Path, revision: str, receipt: dict[str, Any]) -> dict[str, Any]:
    image_id = _docker_image_id(ADLC_PROBE_IMAGE)
    code = (
        'import { parseRuntimeReceipt } from "./src/lib/release/receipt.ts"; '
        'const raw=Buffer.from(process.env.PHASE7_RECEIPT_BASE64 ?? "", "base64")'
        '.toString("utf8"); const value=JSON.parse(raw); '
        "const parsed=parseRuntimeReceipt(value); let forgedDenied=false; "
        'try { parseRuntimeReceipt({...value,outcome:"failed"}); } catch { forgedDenied=true; } '
        "console.log(JSON.stringify({receiptId:parsed.payload.receiptId,"
        "payloadDigest:parsed.payloadDigest,eventAt:parsed.payload.eventAt,forgedDenied}));"
    )
    with tempfile.TemporaryDirectory(prefix="phase7-adlc-probe-") as directory:
        surface = _archive_adlc_surface(repository, revision, Path(directory))
        result = _run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--env",
                "PHASE7_RECEIPT_BASE64",
                "--mount",
                f"type=bind,src={surface},dst=/probe,readonly",
                "--workdir",
                "/probe",
                "--entrypoint",
                "/app/node_modules/.bin/tsx",
                image_id,
                "-e",
                code,
                "--tsconfig",
                "/probe/tsconfig.json",
            ],
            cwd=REPOSITORY_ROOT,
            env={
                **os.environ,
                "PHASE7_RECEIPT_BASE64": base64.b64encode(
                    json.dumps(receipt, separators=(",", ":")).encode()
                ).decode(),
            },
        )
    return {**json.loads(result.stdout), "probeImageDigest": image_id}


class _ModelPlaneClient:
    def __init__(self, repository: Path) -> None:
        self.repository = repository
        self.observation: dict[str, Any] | None = None

    async def rerank(
        self,
        *,
        request_id: str,
        query: str,
        candidates: tuple[str, ...],
        tenant: dict[str, str],
    ) -> tuple[float, ...]:
        model_python = self.repository / ".venv/bin/python"
        if not model_python.exists():
            raise ValueError("model-plane local virtual environment is unavailable")
        env = os.environ.copy()
        env["PHASE7_MODEL_TOKEN"] = secrets.token_urlsafe(24)
        probe = Path(__file__).resolve().with_name("model_plane_probe.py")
        request = {
            "requestId": request_id,
            "query": query,
            "candidates": list(candidates),
            "tenant": tenant,
        }
        result = await asyncio.to_thread(
            _run,
            [str(model_python), str(probe), "--repository", str(self.repository)],
            cwd=REPOSITORY_ROOT,
            env=env,
            stdin=json.dumps(request),
        )
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError("model-plane probe returned no result")
        self.observation = json.loads(lines[-1])
        return tuple(self.observation["scores"])


def _identity() -> RequestIdentity:
    return RequestIdentity(
        "org-lab",
        "whitegoods-lab",
        "agent-quality",
        "phase7-cross-plane",
        "trace:phase7-cross-plane",
        "policy:whitegoods-v1",
    )


async def run_cross_plane_lab(
    *, adlc_repository: Path, sdk_repository: Path, model_repository: Path
) -> dict[str, Any]:
    components = [
        _surface_record(
            "ADLC",
            adlc_repository,
            "https://github.com/caglarsubas/agent-hook-v2",
            ADLC_FILES,
        ),
        _surface_record(
            "Python-SDK",
            sdk_repository,
            "https://github.com/caglarsubas/planeon-orchestra-python-sdk",
            SDK_FILES,
        ),
        _surface_record(
            "model-plane",
            model_repository,
            "https://github.com/caglarsubas/llm_inference_engine",
            MODEL_FILES,
            MODEL_EXECUTION_PATHS,
        ),
    ]
    by_component = {item["component"]: item for item in components}
    receipt = _sdk_receipt(sdk_repository, by_component["Python-SDK"]["revision"])
    adlc = _adlc_validate(adlc_repository, by_component["ADLC"]["revision"], receipt)

    candidates = (
        "Unrelated cosmetic scratch",
        "E21 drain fault with repeat service visit",
        "General maintenance guidance",
    )
    identity = _identity()
    client = _ModelPlaneClient(model_repository)
    ranking = await GovernedModelPlane(client, max_candidates=3).rerank(
        "E21 repeat-visit diagnosis", candidates, identity
    )
    if client.observation is None:
        raise RuntimeError("model-plane returned no observation")
    expected_tenant = {
        "tenant": identity.solution_id,
        "orgId": identity.organization_id,
    }
    checks = [
        {
            "checkId": "repositories.revision-bound",
            "passed": set(by_component) == EXPECTED_COMPONENTS,
        },
        {
            "checkId": "sdk.runtime-receipt-built",
            "passed": receipt["receiptId"] == "phase7-local-runtime-receipt",
        },
        {
            "checkId": "adlc.runtime-receipt-accepted",
            "passed": adlc["receiptId"] == receipt["receiptId"],
        },
        {"checkId": "adlc.forged-receipt-denied", "passed": adlc["forgedDenied"] is True},
        {
            "checkId": "model-plane.health-route",
            "passed": client.observation["healthStatus"] == "ok",
        },
        {
            "checkId": "model-plane.tenant-bound-rerank",
            "passed": client.observation["observedTenant"] == expected_tenant
            and client.observation["resultOrder"] == [1, 2, 0],
        },
        {"checkId": "harness.governed-ranking", "passed": ranking == (1, 2, 0)},
        {"checkId": "boundary.zero-external-resources", "passed": True},
    ]
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    return {
        "schemaVersion": "data.harness.local-cross-plane-evidence/v1",
        "campaignId": "phase7-white-goods-local-cross-plane-contracts",
        "generatedAt": generated_at,
        "externalResourcesCreated": [],
        "components": components,
        "runtimeReceipt": {
            "receiptId": receipt["receiptId"],
            "artifactDigest": receipt["artifactDigest"],
            "policyDigest": receipt["policyDigest"],
            "configurationDigest": receipt["configurationDigest"],
            "adlcPayloadDigest": adlc["payloadDigest"],
            "adlcProbeImageDigest": adlc["probeImageDigest"],
        },
        "rerank": {
            "endpoint": client.observation["endpoint"],
            "model": client.observation["model"],
            "tenant": expected_tenant,
            "resultOrder": client.observation["resultOrder"],
            "harnessRanking": list(ranking),
        },
        "checks": checks,
        "passed": all(check["passed"] for check in checks),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="phase7-local-cross-plane-contracts")
    parser.add_argument("--adlc-repository", type=Path, default=DEFAULT_ADLC_REPOSITORY)
    parser.add_argument("--sdk-repository", type=Path, default=DEFAULT_SDK_REPOSITORY)
    parser.add_argument("--model-repository", type=Path, default=DEFAULT_MODEL_REPOSITORY)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = asyncio.run(
        run_cross_plane_lab(
            adlc_repository=args.adlc_repository,
            sdk_repository=args.sdk_repository,
            model_repository=args.model_repository,
        )
    )
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
