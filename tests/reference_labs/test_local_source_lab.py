import pytest

from reference_labs.white_goods.live.local_lab import validate_local_docker_host
from reference_labs.white_goods.live.service_api import appointment_page


def test_service_api_paginates_and_filters() -> None:
    rows = [
        {"appointment_id": "A1", "service_order_id": "SO1"},
        {"appointment_id": "A2", "service_order_id": "SO2"},
        {"appointment_id": "A3", "service_order_id": "SO1"},
    ]
    assert appointment_page(rows, service_order_id=None, cursor=None, page_size=2) == {
        "items": rows[:2],
        "nextCursor": "2",
    }
    assert appointment_page(rows, service_order_id="SO1", cursor="1", page_size=2) == {
        "items": [rows[2]],
        "nextCursor": None,
    }
    with pytest.raises(ValueError, match="non-negative"):
        appointment_page(rows, service_order_id=None, cursor="bad", page_size=2)


def test_docker_endpoint_must_be_local() -> None:
    validate_local_docker_host('"unix:///Users/example/.docker/run/docker.sock"')
    with pytest.raises(ValueError, match="not laptop-local"):
        validate_local_docker_host("tcp://remote.example:2376")
