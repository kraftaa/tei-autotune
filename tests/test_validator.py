import asyncio
import json

import httpx

from tei_autotune.client import TeiClient
from tei_autotune.models import Constraints, WorkloadItem
from tei_autotune.report import write_validation_outputs
from tei_autotune.validator import validate_fixed_rate


def test_fixed_rate_validation_includes_client_queueing(tmp_path):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/info":
            return httpx.Response(200, json={"max_client_batch_size": 8})
        inputs = json.loads(request.content)["inputs"]
        await asyncio.sleep(0.002)
        return httpx.Response(
            200,
            json=[[1.0] for _ in inputs],
            headers={"x-queue-time": "0.5", "x-inference-time": "1.0"},
        )

    async def exercise():
        return await validate_fixed_rate(
            TeiClient("http://mock", transport=httpx.MockTransport(handler)),
            [WorkloadItem("one"), WorkloadItem("two")],
            batch_size=2,
            concurrency=1,
            arrival_rate_texts_per_second=100,
            duration_seconds=0.06,
            warmup_seconds=0,
            repetitions=2,
            constraints=Constraints(100, 0, 1, 1),
        )

    result = asyncio.run(exercise())
    json_path, report_path = write_validation_outputs(result, tmp_path)

    assert result.passed
    assert result.cell.offered_texts_per_second is not None
    assert result.cell.schedule_lag_p95_ms is not None
    assert json.loads(json_path.read_text())["passed"] is True
    assert "# TEI AutoTune fixed-rate validation" in report_path.read_text()


def test_overload_drops_arrivals_instead_of_growing_without_bound():
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.005)
        inputs = json.loads(request.content)["inputs"]
        return httpx.Response(200, json=[[1.0] for _ in inputs])

    async def exercise():
        return await TeiClient(
            "http://mock", transport=httpx.MockTransport(handler)
        ).run_open_loop(
            [WorkloadItem("one")],
            batch_size=1,
            concurrency=1,
            arrival_rate_texts_per_second=10_000,
            duration_seconds=0.02,
            warmup_seconds=0,
            repetition=0,
        )

    result = asyncio.run(exercise())

    assert result.status_counts["client_queue_full"] > 0
    assert result.failed_requests > 0
    assert result.requests == result.offered_texts
