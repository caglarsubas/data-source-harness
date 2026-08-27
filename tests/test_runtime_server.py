import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from data_source_harness import __version__, runtime_server
from data_source_harness.runtime_server import RuntimeStatusHandler


def test_runtime_health_readiness_version_and_not_found() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), RuntimeStatusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        for path, expected_status in (
            ("/healthz", "healthy"),
            ("/readyz", "ready"),
        ):
            with urlopen(base + path, timeout=1) as response:  # noqa: S310 - loopback test
                payload = json.load(response)
            assert payload == {"status": expected_status, "version": __version__}
            assert response.headers["Cache-Control"] == "no-store"
        with urlopen(base + "/version", timeout=1) as response:  # noqa: S310
            assert json.load(response) == {"version": __version__}
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/missing", timeout=1)  # noqa: S310
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_runtime_main_serves_and_closes(monkeypatch) -> None:
    state = {"served": False, "closed": False, "address": None}

    class FakeServer:
        def __init__(self, address, handler):
            state["address"] = address
            assert handler is RuntimeStatusHandler

        def serve_forever(self):
            state["served"] = True
            raise KeyboardInterrupt

        def server_close(self):
            state["closed"] = True

    monkeypatch.setattr(runtime_server, "ThreadingHTTPServer", FakeServer)
    assert runtime_server.main(["--bind", "127.0.0.1", "--port", "8181"]) == 0
    assert state == {
        "served": True,
        "closed": True,
        "address": ("127.0.0.1", 8181),
    }
    with pytest.raises(SystemExit):
        runtime_server.main(["--port", "0"])
