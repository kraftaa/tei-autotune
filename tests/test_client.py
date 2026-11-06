import asyncio
import json

import httpx

from tei_autotune.client import TeiClient
from tei_autotune.models import WorkloadItem


def test_client_discovers_server_and_measures_cell():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/info":
            return httpx.Response(
                200, json={"model_id": "mock/model", "max_client_batch_size": 8}
            )
        if request.url.path == "/embed":
            payload = json.loads(request.content)
            inputs = payload["inputs"]
            await asyncio.sleep(0.005)
            return httpx.Response(
                200,
                json=[[float(len(text)), 1.0] for text in inputs],
                headers={
                    "x-compute-tokens": str(len(inputs) * 3),
                    "x-queue-time": "1.5",
                    "x-tokenization-time": "2.5",
                    "x-inference-time": "5.5",
                    "x-total-time": "9.5",
                },
            )
        return httpx.Response(404)

    async def exercise():
        client = TeiClient(
            "http://mock-tei",
            timeout_seconds=2,
            transport=httpx.MockTransport(handler),
        )
        assert (await client.get_info())["max_client_batch_size"] == 8
        runs = await client.run_cell(
            [WorkloadItem("one"), WorkloadItem("two")],
            batch_size=2,
            concurrency=2,
            duration_seconds=0.08,
            warmup_seconds=0.01,
            repetitions=1,
        )
        return runs[0]

    result = asyncio.run(exercise())

    assert result.successful_requests > 0
    assert result.successful_texts == result.successful_requests * 2
    assert result.compute_tokens == result.successful_requests * 6
    assert result.error_rate == 0
    assert result.p95_ms > 0
    assert result.p95_ms >= result.transport_p95_ms
    assert result.decode_p95_ms > 0
    assert result.client_cpu_seconds > 0
    assert result.server_queue_p50_ms == 1.5
    assert result.server_inference_p50_ms == 5.5
