from data_source_harness.decoder import DecoderRegistry, PayloadFormat


class FakeDecoder:
    decoder_id = "json-v1"
    supported_formats = frozenset({PayloadFormat.JSON})


def test_decoder_registry_is_capability_based() -> None:
    registry = DecoderRegistry()
    decoder = FakeDecoder()
    registry.register(decoder)  # type: ignore[arg-type]
    assert registry.get(PayloadFormat.JSON) is decoder


def test_decoder_registry_rejects_ambiguous_format_ownership() -> None:
    registry = DecoderRegistry()
    registry.register(FakeDecoder())  # type: ignore[arg-type]
    try:
        registry.register(FakeDecoder())  # type: ignore[arg-type]
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("duplicate decoder format was accepted")
