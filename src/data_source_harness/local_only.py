"""Static guardrails for the laptop-local operating boundary."""

from __future__ import annotations

import re
from pathlib import Path

PROHIBITED_AUTOMATION = (
    ("gcp-cli", re.compile(r"\b(?:gcloud|gsutil)\s+", re.IGNORECASE)),
    (
        "cluster-cli",
        re.compile(
            r"\b(?:oc|kubectl)\s+(?:apply|create|delete|deploy|new-app|patch|replace|scale)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "infrastructure-apply",
        re.compile(r"\b(?:terraform|tofu|pulumi)\s+(?:apply|destroy|up)\b", re.IGNORECASE),
    ),
    (
        "cloud-deploy-action",
        re.compile(r"(?:google-github-actions|redhat-actions)/(?:auth|deploy|setup-gcloud)", re.I),
    ),
    (
        "remote-container-engine",
        re.compile(
            r"(?:\bDOCKER_HOST\s*=\s*(?:tcp|ssh)://|\bdocker\s+context\s+use\b|"
            r"\bpodman\s+--remote\b)",
            re.IGNORECASE,
        ),
    ),
)

AUTOMATION_ROOTS = (
    Path(".github/workflows"),
    Path("scripts"),
    Path("src"),
    Path("reference_labs"),
    Path("Makefile"),
)
TEXT_AUTOMATION_SUFFIXES = frozenset({".py", ".sh", ".yml", ".yaml", ".toml"})


def audit_local_only_automation(repository_root: Path) -> tuple[str, ...]:
    """Return stable violations from executable automation surfaces."""

    violations: list[str] = []
    for relative_root in AUTOMATION_ROOTS:
        target = repository_root / relative_root
        paths = (
            [target]
            if target.is_file()
            else sorted(
                path
                for path in target.rglob("*")
                if path.is_file() and path.suffix in TEXT_AUTOMATION_SUFFIXES
            )
        )
        for path in paths:
            relative_path = path.relative_to(repository_root)
            if relative_path in {
                Path("scripts/check-local-only.py"),
                Path("src/data_source_harness/local_only.py"),
            }:
                continue
            text = path.read_text(encoding="utf-8")
            for rule, pattern in PROHIBITED_AUTOMATION:
                if pattern.search(text):
                    violations.append(f"{relative_path}:{rule}")
    return tuple(violations)


def assert_local_only_automation(repository_root: Path) -> None:
    violations = audit_local_only_automation(repository_root)
    if violations:
        raise ValueError("prohibited cloud or cluster automation: " + ", ".join(violations))
