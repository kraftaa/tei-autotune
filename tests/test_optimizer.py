from tei_autotune.models import CellResult, RunResult
from tei_autotune.optimizer import choose_recommendation, pareto_frontier


def cell(batch, concurrency, throughput, latency):
    duration = 10.0
    throughputs = throughput if isinstance(throughput, list) else [throughput]
    runs = [
        RunResult(
            batch_size=batch,
            concurrency=concurrency,
            repetition=index,
            duration_seconds=duration,
            successful_requests=100,
            failed_requests=0,
            successful_texts=int(value * duration),
            compute_tokens=0,
            latencies_ms=[latency] * 100,
        )
        for index, value in enumerate(throughputs)
    ]
    return CellResult(batch, concurrency, runs)


def test_prefers_lower_concurrency_within_three_percent_of_peak():
    lower = cell(8, 4, [970, 980, 990], 100)
    peak = cell(8, 8, [980, 1000, 1020], 150)

    assert choose_recommendation([lower, peak]) is lower


def test_does_not_sacrifice_more_than_three_percent():
    lower = cell(8, 4, [945, 950, 955], 100)
    peak = cell(8, 8, [995, 1000, 1005], 150)

    assert choose_recommendation([lower, peak]) is peak


def test_pareto_frontier_removes_dominated_cell():
    slow = cell(1, 1, 100, 20)
    dominated = cell(8, 4, 200, 100)
    better = cell(8, 8, 300, 80)

    assert pareto_frontier([slow, dominated, better]) == [slow, better]


def test_never_recommends_zero_throughput():
    failed = cell(1, 1, 0, 0)

    assert choose_recommendation([failed]) is None


def test_rejects_undersampled_or_unstable_cells():
    undersampled = cell(8, 4, [100, 100, 100], 50)
    for run in undersampled.runs:
        run.successful_requests = 10
    unstable = cell(8, 8, [50, 100, 150], 50)

    assert not undersampled.satisfies(100, 0, min_successful_requests=100)
    assert not unstable.satisfies(100, 0, max_throughput_cv=0.10)
