"""Source-neutral decoding boundary for untrusted source bytes."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any, Protocol

from .models import BatchKind, DataBatch, LineageRef, SourceVersion


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
class DecoderLimits:
    max_payload_bytes: int = 4 * 1024 * 1024
    max_records: int = 10_000
    max_text_characters: int = 2_000_000

    def __post_init__(self) -> None:
        if min(self.max_payload_bytes, self.max_records, self.max_text_characters) <= 0:
            raise ValueError("decoder limits must be positive")


class DecodeRejected(ValueError):
    pass


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

    @classmethod
    def with_standard_decoders(cls, limits: DecoderLimits | None = None) -> DecoderRegistry:
        registry = cls()
        registry.register(StandardDecoder(limits or DecoderLimits()))
        return registry


class _SafeHTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []
        self._ignored_depth = 0
        self.active_content_removed = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "template", "noscript"}:
            self._ignored_depth += 1
            self.active_content_removed = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "template", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.fragments.append(data.strip())


class StandardDecoder:
    """Bounded decoders for safe structured/text formats in the core distribution."""

    decoder_id = "data.harness.standard/v1"
    supported_formats = frozenset(
        {PayloadFormat.CSV, PayloadFormat.JSON, PayloadFormat.HTML, PayloadFormat.TEXT}
    )
    _media_types = {
        PayloadFormat.CSV: {"text/csv", "application/csv"},
        PayloadFormat.JSON: {"application/json", "application/jsonl", "application/x-ndjson"},
        PayloadFormat.HTML: {"text/html", "application/xhtml+xml"},
        PayloadFormat.TEXT: {"text/plain", "text/markdown"},
    }
    _injection_markers = (
        "ignore previous instructions",
        "ignore all previous",
        "system prompt",
        "developer message",
    )

    def __init__(self, limits: DecoderLimits | None = None) -> None:
        self.limits = limits or DecoderLimits()

    async def decode(self, request: DecodeRequest) -> DecodeResult:
        if len(request.payload) > self.limits.max_payload_bytes:
            raise DecodeRejected("payload exceeds decoder byte limit")
        if request.media_type.lower() not in self._media_types[request.payload_format]:
            raise DecodeRejected("media type does not match the declared payload format")
        try:
            text = request.payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise DecodeRejected("payload is not valid UTF-8") from exc
        if len(text) > self.limits.max_text_characters:
            raise DecodeRejected("decoded text exceeds character limit")

        warnings = self._warnings(text)
        if request.payload_format is PayloadFormat.JSON:
            try:
                payload, rows = self._json(text, request.media_type.lower())
            except (json.JSONDecodeError, RecursionError) as exc:
                raise DecodeRejected("payload is not valid bounded JSON") from exc
            kind = BatchKind.ARROW if isinstance(payload, list) else BatchKind.DOCUMENT
        elif request.payload_format is PayloadFormat.CSV:
            try:
                payload = list(csv.DictReader(io.StringIO(text)))
            except csv.Error as exc:
                raise DecodeRejected("payload is not valid bounded CSV") from exc
            rows = len(payload)
            kind = BatchKind.ARROW
        elif request.payload_format is PayloadFormat.HTML:
            parser = _SafeHTMLText()
            parser.feed(text)
            payload = {"content": "\n".join(parser.fragments), "media_type": request.media_type}
            rows = 1
            kind = BatchKind.DOCUMENT
            if parser.active_content_removed:
                warnings = (*warnings, "active-html-content-removed")
        else:
            payload = {"content": text, "media_type": request.media_type}
            rows = 1
            kind = BatchKind.DOCUMENT
        if rows > self.limits.max_records:
            raise DecodeRejected("decoded record count exceeds limit")
        return DecodeResult(
            (
                DataBatch(
                    kind,
                    payload,
                    (request.source_version,),
                    request.lineage,
                    row_count=rows,
                    byte_count=len(request.payload),
                ),
            ),
            warnings=warnings,
        )

    def _json(self, text: str, media_type: str) -> tuple[Any, int]:
        def reject_constant(value: str) -> None:
            raise DecodeRejected(f"non-finite JSON constant rejected: {value}")

        if media_type in {"application/jsonl", "application/x-ndjson"}:
            values = [
                json.loads(line, parse_constant=reject_constant)
                for line in text.splitlines()
                if line.strip()
            ]
            return values, len(values)
        value = json.loads(text, parse_constant=reject_constant)
        return value, len(value) if isinstance(value, list) else 1

    def _warnings(self, text: str) -> tuple[str, ...]:
        lowered = text.lower()
        if any(marker in lowered for marker in self._injection_markers):
            return ("potential-prompt-injection",)
        return ()
