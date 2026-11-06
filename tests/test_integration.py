import asyncio
import json

import httpx

from tei_autotune.client import TeiClient
from tei_autotune.models import Constraints, WorkloadItem
from tei_autotune.optimizer import optimize
from tei_autotune.report import write_checkpoint, write_outputs


def test_optimizer_filters_server_limit_and_writes_artifacts(tmp_path):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/info":
            return httpx.Response(
                200,
                json={
                    "model_id": "mock/model",
                    "version": "test",
                    "max_client_batch_size": 2,
                    "max_batch_tokens": 1024,
                },
            )
        payload = json.loads(request.content)
        inputs = payload["inputs"]
        await asyncio.sleep(0.001)
        return httpx.Response(
            200,
            json=[[1.0, 2.0] for _ in inputs],
            headers={"x-compute-tokens": str(len(inputs) * 4)},
        )

    async def exercise():
        client = TeiClient(
            "http://mock-tei", transport=httpx.MockTransport(handler)
        )
        return await optimize(
            client,
            [WorkloadItem("one"), WorkloadItem("a longer input")],
            batch_sizes=[1, 2, 4],
            concurrencies=[1, 2],
            constraints=Constraints(
                max_p95_ms=100,
                max_error_rate=0,
                min_successful_requests=1,
                max_throughput_cv=1,
            ),
            duration_seconds=0.025,
            warmup_seconds=0,
            repetitions=1,
            baseline_batch=1,
            baseline_concurrency=1,
            hourly_price=1.0,
        )

    result = asyncio.run(exercise())
    json_path, report_path = write_outputs(result, tmp_path)

    assert {cell.batch_size for cell in result.cells} == {1, 2}
    assert result.recommended is not None
    raw = json.loads(json_path.read_text())
    assert raw["schema_version"] == 2
    assert raw["recommended"] is not None
    report = report_path.read_text()
    assert "mock/model" in report
    assert "theoretical saturated-capacity cost" in report.lower()
    assert "does not reproduce an application's arrival pattern" in report

    checkpoint_path = write_checkpoint(
        endpoint=result.endpoint,
        cells=result.cells,
        completed_runs=4,
        total_runs=4,
        output_dir=tmp_path,
    )
    checkpoint = json.loads(checkpoint_path.read_text())
    assert checkpoint["status"] == "complete"
    assert checkpoint["completed_runs"] == checkpoint["total_runs"]
    assert not (tmp_path / "results.partial.json.tmp").exists()
