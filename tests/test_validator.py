import asyncio
import json

import httpx

from tei_autotune.client import TeiClient
from tei_autotune.models import (
    CellResult,
    Constraints,
    RunResult,
    ValidationResult,
    WorkloadItem,
)
from tei_autotune.report import (
    _diagnose_cell,
    render_rate_discovery_markdown,
    write_validation_outputs,
)
from tei_autotune.validator import discover_safe_rate, validate_fixed_rate


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


def test_scheduling_lag_does_not_claim_more_concurrency_will_help():
    run = RunResult(
        batch_size=1,
        concurrency=2,
        repetition=0,
        duration_seconds=10,
        successful_requests=100,
        failed_requests=0,
        successful_texts=100,
        compute_tokens=0,
        latencies_ms=[400] * 100,
        schedule_lag_ms=[300] * 100,
    )

    diagnostic = _diagnose_cell(CellResult(1, 2, [run]))

    assert "offered load exceeds" in diagnostic.lower()
    assert "higher concurrency will increase capacity" in diagnostic.lower()


def test_rate_discovery_tolerates_one_failure_and_stops_after_two(monkeypatch):
    outcomes = {25.0: True, 26.0: False, 27.0: True, 28.0: False, 29.0: False}

    async def fake_validate(client, corpus, **kwargs):
        rate = kwargs["arrival_rate_texts_per_second"]
        run = RunResult(
            batch_size=1,
            concurrency=2,
            repetition=0,
            duration_seconds=1,
            successful_requests=100,
            failed_requests=0,
            successful_texts=int(rate),
            compute_tokens=0,
            latencies_ms=[50] * 100,
        )
        return ValidationResult(
            endpoint="http://mock",
            server_info={},
            corpus_summary={"items": 1},
            constraints=kwargs["constraints"],
            target_texts_per_second=rate,
            cell=CellResult(1, 2, [run]),
            passed=outcomes[rate],
        )

    monkeypatch.setattr("tei_autotune.validator.validate_fixed_rate", fake_validate)

    result = asyncio.run(
        discover_safe_rate(
            object(),
            [WorkloadItem("text")],
            batch_size=1,
            concurrency=2,
            min_rate=25,
            max_rate=35,
            step=1,
            failure_window=2,
            duration_seconds=1,
            warmup_seconds=0,
            repetitions=1,
            constraints=Constraints(200, 0.01),
        )
    )

    assert [item.target_texts_per_second for item in result.validations] == [
        25,
        26,
        27,
        28,
        29,
    ]
    assert result.recommended is not None
    assert result.recommended.target_texts_per_second == 27
    assert result.non_monotonic
    assert result.stopped_early
    report = render_rate_discovery_markdown(result)
    assert "27 texts/s" in report
    assert "boundary as noisy" in report
