import json

from tei_autotune.models import (
    CellResult,
    Constraints,
    OptimizationResult,
    RateDiscoveryResult,
    RunResult,
    ValidationResult,
)
from tei_autotune.pipeline import derive_rate_plan, write_run_summary


def _cell(batch=1, concurrency=2, throughput=36, latency=80):
    return CellResult(
        batch,
        concurrency,
        [
            RunResult(
                batch_size=batch,
                concurrency=concurrency,
                repetition=0,
                duration_seconds=10,
                successful_requests=int(throughput * 10),
                failed_requests=0,
                successful_texts=int(throughput * 10),
                compute_tokens=0,
                latencies_ms=[latency] * 100,
            )
        ],
    )


def test_derive_rate_plan_brackets_measured_capacity():
    minimum, maximum, step = derive_rate_plan(36.8)

    assert (minimum, maximum, step) == (14.7, 40.7, 3.7)
    assert minimum <= 36.8 * 0.4
    assert maximum >= 36.8 * 1.1


def test_rate_plan_includes_a_headroom_candidate_below_half_capacity():
    minimum, _, step = derive_rate_plan(38.1)

    assert minimum == 15.2
    assert minimum + step <= 38.1 * 0.51


def test_writes_one_command_summary(tmp_path):
    constraints = Constraints(200, 0.01, 10, 0.10)
    recommended_cell = _cell()
    optimization = OptimizationResult(
        endpoint="http://mock",
        server_info={},
        corpus_summary={"items": 1},
        constraints=constraints,
        cells=[recommended_cell],
        recommended=recommended_cell,
        baseline=recommended_cell,
        hourly_price=None,
        strategy="adaptive",
    )
    validation = ValidationResult(
        endpoint="http://mock",
        server_info={},
        corpus_summary={"items": 1},
        constraints=constraints,
        target_texts_per_second=28,
        cell=_cell(throughput=28, latency=100),
        passed=True,
    )
    discovery = RateDiscoveryResult(
        endpoint="http://mock",
        server_info={},
        corpus_summary={"items": 1},
        constraints=constraints,
        batch_size=1,
        concurrency=2,
        min_rate=18,
        max_rate=40,
        step=4,
        failure_window=2,
        headroom=0.10,
        confirmation_enabled=True,
        confirmation_cooldown_seconds=5,
        validations=[validation],
        confirmations=[validation],
        ramp_recommended=validation,
        recommended=validation,
        production_rate=24,
        stopped_early=True,
        non_monotonic=False,
    )

    markdown_path, json_path = write_run_summary(
        optimization, discovery, tmp_path, thorough=False
    )

    markdown = markdown_path.read_text()
    summary = json.loads(json_path.read_text())
    assert "Batch size: **1**" in markdown
    assert "Suggested production rate: **24 texts/s**" in markdown
    assert summary["confirmed_rate"] == 28
    assert summary["production_rate"] == 24
