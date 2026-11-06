import asyncio
import json

import httpx

from tei_autotune.client import TeiClient
from tei_autotune.models import Constraints, WorkloadItem
from tei_autotune.optimizer import _coarse_configurations, optimize


def test_repetitions_are_interleaved_by_randomized_round():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/info":
            return httpx.Response(200, json={"max_client_batch_size": 8})
        inputs = json.loads(request.content)["inputs"]
        return httpx.Response(200, json=[[1.0] for _ in inputs])

    progress_messages = []

    async def exercise():
        return await optimize(
            TeiClient("http://mock", transport=httpx.MockTransport(handler)),
            [WorkloadItem("one"), WorkloadItem("two")],
            batch_sizes=[1, 2],
            concurrencies=[1, 2],
            constraints=Constraints(100, 0, 1, 1),
            duration_seconds=0.002,
            warmup_seconds=0,
            repetitions=2,
            baseline_batch=1,
            baseline_concurrency=1,
            hourly_price=None,
            seed=7,
            progress=progress_messages.append,
        )

    result = asyncio.run(exercise())

    assert all("run=1/2" in message for message in progress_messages[:4])
    assert all("run=2/2" in message for message in progress_messages[4:])
    assert all([run.repetition for run in cell.runs] == [0, 1] for cell in result.cells)


def test_adaptive_coarse_grid_includes_boundaries_and_baseline():
    configurations = _coarse_configurations(
        [1, 8, 16, 32], [1, 2, 4, 8, 16], (8, 2)
    )

    assert (1, 1) in configurations
    assert (32, 16) in configurations
    assert (8, 2) in configurations
    assert len(configurations) < 4 * 5
