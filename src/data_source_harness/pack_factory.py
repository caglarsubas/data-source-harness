"""Deterministic, metadata-driven synthetic dataset generation for industry packs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any


class FieldKind(StrEnum):
    SEQUENCE = "sequence"
    CHOICE = "choice"
    INTEGER = "integer"
    TIMESTAMP = "timestamp"
    REFERENCE = "reference"


@dataclass(frozen=True)
class FieldBlueprint:
    name: str
    kind: FieldKind
    values: tuple[str, ...] = ()
    minimum: int = 0
    maximum: int = 100
    prefix: str = "id"
    reference_dataset: str | None = None
    reference_field: str | None = None
    weights: tuple[float, ...] = ()
    null_rate: float = 0.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("field name is required")
        if self.kind is FieldKind.CHOICE and not self.values:
            raise ValueError(f"choice field {self.name!r} requires values")
        if self.weights and (
            self.kind is not FieldKind.CHOICE
            or len(self.weights) != len(self.values)
            or any(not math.isfinite(weight) or weight <= 0 for weight in self.weights)
        ):
            raise ValueError(f"weights for {self.name!r} must match choices and be positive")
        if not math.isfinite(self.null_rate) or not 0 <= self.null_rate < 1:
            raise ValueError(f"null rate for {self.name!r} must be in [0, 1)")
        if self.kind is FieldKind.SEQUENCE and self.null_rate:
            raise ValueError(f"sequence field {self.name!r} cannot be nullable")
        if self.kind is FieldKind.INTEGER and self.minimum > self.maximum:
            raise ValueError(f"invalid integer range for {self.name!r}")
        if self.kind is FieldKind.REFERENCE and (
            not self.reference_dataset or not self.reference_field
        ):
            raise ValueError(f"reference field {self.name!r} requires a dataset and field")


@dataclass(frozen=True)
class DatasetBlueprint:
    dataset_id: str
    row_count: int
    fields: tuple[FieldBlueprint, ...]

    def __post_init__(self) -> None:
        if not self.dataset_id or self.row_count <= 0 or not self.fields:
            raise ValueError("dataset id, positive row count and fields are required")
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate fields in dataset {self.dataset_id!r}")


@dataclass(frozen=True)
class IndustryPackDefinition:
    pack_id: str
    version: str
    seed: int
    datasets: tuple[DatasetBlueprint, ...]

    def __post_init__(self) -> None:
        ids = [dataset.dataset_id for dataset in self.datasets]
        if not self.pack_id or not self.version or not self.datasets:
            raise ValueError("pack id, version and datasets are required")
        if len(ids) != len(set(ids)):
            raise ValueError("dataset ids must be unique")


GeneratedPack = dict[str, tuple[dict[str, Any], ...]]


class MockDatasetGenerator:
    """Generate relationship-safe records with no network or external dependencies."""

    _epoch = datetime(2026, 1, 1, tzinfo=UTC)

    def generate(self, definition: IndustryPackDefinition) -> GeneratedPack:
        generated: GeneratedPack = {}
        pending = list(definition.datasets)
        while pending:
            progressed = False
            for dataset in tuple(pending):
                references = {
                    field.reference_dataset
                    for field in dataset.fields
                    if field.kind is FieldKind.REFERENCE
                }
                if not references.issubset(generated):
                    continue
                generated[dataset.dataset_id] = self._generate_dataset(
                    definition, dataset, generated
                )
                pending.remove(dataset)
                progressed = True
            if not progressed:
                unresolved = ", ".join(item.dataset_id for item in pending)
                raise ValueError(f"cyclic or unknown dataset references: {unresolved}")
        return generated

    def _generate_dataset(
        self,
        definition: IndustryPackDefinition,
        dataset: DatasetBlueprint,
        generated: GeneratedPack,
    ) -> tuple[dict[str, Any], ...]:
        seed_material = (
            f"{definition.pack_id}:{definition.version}:{definition.seed}:{dataset.dataset_id}"
        )
        seed = int.from_bytes(hashlib.sha256(seed_material.encode()).digest()[:8], "big")
        rng = random.Random(seed)
        records: list[dict[str, Any]] = []
        for index in range(dataset.row_count):
            record: dict[str, Any] = {}
            for field in dataset.fields:
                if field.kind is FieldKind.SEQUENCE:
                    value: Any = f"{field.prefix}-{index + 1:04d}"
                elif field.null_rate and rng.random() < field.null_rate:
                    value = None
                elif field.kind is FieldKind.CHOICE:
                    value = (
                        rng.choices(field.values, weights=field.weights, k=1)[0]
                        if field.weights
                        else field.values[rng.randrange(len(field.values))]
                    )
                elif field.kind is FieldKind.INTEGER:
                    value = rng.randint(field.minimum, field.maximum)
                elif field.kind is FieldKind.TIMESTAMP:
                    value = (self._epoch + timedelta(minutes=rng.randint(0, 525_600))).isoformat()
                else:
                    referenced = generated[field.reference_dataset or ""]
                    target = referenced[index % len(referenced)]
                    value = target[field.reference_field or ""]
                record[field.name] = value
            records.append(record)
        return tuple(records)

    @staticmethod
    def render_jsonl(records: tuple[Mapping[str, Any], ...]) -> bytes:
        return b"".join(
            (json.dumps(dict(record), sort_keys=True, separators=(",", ":")) + "\n").encode()
            for record in records
        )

    @staticmethod
    def render_csv(records: tuple[Mapping[str, Any], ...]) -> bytes:
        if not records:
            raise ValueError("cannot render an empty dataset")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
        return output.getvalue().encode()

    def write_jsonl(self, definition: IndustryPackDefinition, output: Path) -> dict[str, str]:
        generated = self.generate(definition)
        output.mkdir(parents=True, exist_ok=True)
        digests: dict[str, str] = {}
        for dataset_id, records in sorted(generated.items()):
            payload = self.render_jsonl(records)
            target = output / f"{dataset_id}.jsonl"
            target.write_bytes(payload)
            digests[target.name] = hashlib.sha256(payload).hexdigest()
        return digests
