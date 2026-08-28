from pathlib import Path

import pytest

from reference_labs.white_goods.live.cross_plane_lab import (
    _ModelPlaneClient,
    _surface_record,
)


def test_cross_plane_surface_requires_local_git_checkout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="local Git checkout"):
        _surface_record("ADLC", tmp_path, "https://github.com/example/adlc", ("receipt.ts",))


async def test_model_plane_probe_requires_existing_local_environment(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="virtual environment"):
        await _ModelPlaneClient(tmp_path).rerank(
            request_id="request-1",
            query="E21",
            candidates=("one", "two", "three"),
            tenant={
                "organizationId": "org-lab",
                "solutionId": "whitegoods-lab",
                "agentId": "agent-quality",
            },
        )
