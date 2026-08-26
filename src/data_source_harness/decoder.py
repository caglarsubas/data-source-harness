"""Source-neutral decoding boundary for untrusted source bytes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .models import DataBatch, LineageRef, SourceVersion


class PayloadFormat(StrEnum):
    CSV = "csv"
    JSON = "json"
    HTML = "html"
    PDF = "pdf"
    TEXT = "text"
    ARROW = "arrow"


class ContentTrust(StrEnum):
    UNTRUSTED_SOURCE = "untrusted-source"


@dataclass(frozen=True)
class DecodeRequest:
    payload: bytes
    payload_format: PayloadFormat
    source_version: SourceVersion
    lineage: tuple[LineageRef, ...]
    media_type: str

    def __post_init__(self) -> None:
        if not self.payload or not self.lineage or not self.media_type:
            raise ValueError("decode requests require payload, media type and lineage")


@dataclass(frozen=True)
class DecodeResult:
    batches: tuple[DataBatch, ...]
    trust: ContentTrust = ContentTrust.UNTRUSTED_SOURCE
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.batches:
            raise ValueError("decoder must produce at least one lineage-bearing batch")


class Decoder(Protocol):
    decoder_id: str
    supported_formats: frozenset[PayloadFormat]

    async def decode(self, request: DecodeRequest) -> DecodeResult: ...


class DecoderRegistry:
    def __init__(self) -> None:
        self._decoders: dict[PayloadFormat, Decoder] = {}

    def register(self, decoder: Decoder) -> None:
        if not decoder.supported_formats:
            raise ValueError("decoder must advertise at least one format")
        collisions = set(decoder.supported_formats) & self._decoders.keys()
        if collisions:
            raise ValueError(f"decoder format already registered: {sorted(collisions)}")
        for payload_format in decoder.supported_formats:
            self._decoders[payload_format] = decoder

    def get(self, payload_format: PayloadFormat) -> Decoder:
        try:
            return self._decoders[payload_format]
        except KeyError as exc:
            raise KeyError(f"no decoder for format: {payload_format.value}") from exc
