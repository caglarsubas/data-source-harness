"""Exercise the real model-plane rerank route with a deterministic local adapter."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any


def _load_request() -> dict[str, Any]:
    value = json.load(sys.stdin)
    if not isinstance(value, dict):
        raise ValueError("model-plane probe input must be an object")
    return value


def run_probe(repository: Path, request: dict[str, Any]) -> dict[str, Any]:
    repository = repository.resolve()
    sys.path.insert(0, str(repository / "src"))

    from fastapi.testclient import TestClient
    from inference_engine import auth
    from inference_engine.adapters import (
        EmbeddingResult,
        GenerationParams,
        InferenceAdapter,
        StreamChunk,
    )
    from inference_engine.adapters.base import GenerationResult
    from inference_engine.api import rerank as rerank_api
    from inference_engine.api.state import app_state
    from inference_engine.cancellation import Cancellation
    from inference_engine.config import settings
    from inference_engine.main import app
    from inference_engine.registry import ModelDescriptor

    query = request["query"]
    candidates = request["candidates"]
    tenant = request["tenant"]
    token = os.environ.pop("PHASE7_MODEL_TOKEN")

    class DeterministicAdapter(InferenceAdapter):
        backend_name = "phase7-deterministic"

        @property
        def is_loaded(self) -> bool:
            return True

        @property
        def loaded_model(self) -> ModelDescriptor | None:
            return None

        async def load(self, descriptor: ModelDescriptor) -> None:
            del descriptor

        async def unload(self) -> None:
            return None

        async def generate(
            self,
            messages: Iterable,
            params: GenerationParams,
            cancel: Cancellation | None = None,
        ) -> GenerationResult:
            del messages, params, cancel
            return GenerationResult(
                text="", finish_reason="stop", prompt_tokens=0, completion_tokens=0
            )

        async def stream(
            self,
            messages: Iterable,
            params: GenerationParams,
            cancel: Cancellation | None = None,
        ) -> AsyncIterator[StreamChunk]:
            del messages, params, cancel
            yield StreamChunk(text="", finish_reason="stop")

        async def embed(self, inputs: list[str]) -> EmbeddingResult:
            vectors = {
                query: [1.0, 0.0, 0.0],
                candidates[0]: [-1.0, 0.0, 0.0],
                candidates[1]: [1.0, 0.0, 0.0],
                candidates[2]: [0.0, 1.0, 0.0],
            }
            return EmbeddingResult(
                embeddings=[vectors[value] for value in inputs],
                prompt_tokens=len(inputs),
            )

    adapter = DeterministicAdapter()
    descriptor = ModelDescriptor(
        name="phase7",
        tag="deterministic",
        namespace="local",
        registry="reference-lab",
        model_path=Path("/nonexistent/phase7-deterministic.gguf"),
        format="gguf",
        size_bytes=1,
    )

    async def get_model(_model_id: str) -> tuple[InferenceAdapter, ModelDescriptor]:
        return adapter, descriptor

    observed_identity: dict[str, str | None] = {}
    original_acquire_slot = rerank_api.acquire_slot

    async def capture_slot(*, identity, **kwargs):
        observed_identity.update({"tenant": identity.tenant, "orgId": identity.org_id})
        return await original_acquire_slot(identity=identity, **kwargs)

    settings.auth_enabled = True
    settings.model_plane_workload_surface = "unrestricted"
    settings.model_plane_runtime_control_enabled = False
    settings.batch_max_wait_ms = 0.1
    auth._set_keys_for_tests([(token, tenant["solutionId"], tenant["organizationId"])])
    app_state.manager.get = get_model  # type: ignore[method-assign]
    rerank_api.acquire_slot = capture_slot
    app_state.mark_ready()
    try:
        client = TestClient(app)
        health = client.get("/v1/health")
        response = client.post(
            "/v1/rerank",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "model": "phase7:deterministic",
                "query": query,
                "documents": candidates,
                "return_documents": False,
            },
        )
    finally:
        rerank_api.acquire_slot = original_acquire_slot
        auth._reset_for_tests()

    if health.status_code != 200 or response.status_code != 200:
        raise RuntimeError(
            f"model-plane probe failed: health={health.status_code}; rerank={response.status_code}"
        )
    body = response.json()
    scores = [0.0] * len(candidates)
    for result in body["results"]:
        scores[result["index"]] = result["relevance_score"]
    return {
        "endpoint": "/v1/rerank",
        "healthStatus": health.json()["status"],
        "model": body["model"],
        "observedTenant": observed_identity,
        "resultOrder": [item["index"] for item in body["results"]],
        "scores": scores,
        "usage": body["usage"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="phase7-model-plane-probe")
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run_probe(args.repository, _load_request()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
