from __future__ import annotations

import random
from typing import Any, Callable

from .client import TeiClient
from .corpus import summarize_corpus
from .models import (
    CellResult,
    Constraints,
    OptimizationResult,
    RunResult,
    WorkloadItem,
)


async def optimize(
    client: TeiClient,
    corpus: list[WorkloadItem],
    *,
    batch_sizes: list[int],
    concurrencies: list[int],
    constraints: Constraints,
    duration_seconds: float,
    warmup_seconds: float,
    repetitions: int,
    baseline_batch: int,
    baseline_concurrency: int,
    hourly_price: float | None,
    seed: int = 42,
    strategy: str = "grid",
    progress: Callable[[str], None] | None = None,
    checkpoint: Callable[[list[CellResult], int, int], None] | None = None,
) -> OptimizationResult:
    server_info = await client.get_info()
    max_client_batch_size = _positive_int(server_info.get("max_client_batch_size"))
    if max_client_batch_size:
        batch_sizes = [size for size in batch_sizes if size <= max_client_batch_size]
    if not batch_sizes:
        raise ValueError("all requested batch sizes exceed the server limit")

    await client.check_embed(corpus[0].text)

    all_configurations = [
        (batch_size, concurrency)
        for batch_size in sorted(set(batch_sizes))
        for concurrency in sorted(set(concurrencies))
    ]
    runs_by_configuration: dict[tuple[int, int], list[RunResult]] = {
        configuration: [] for configuration in all_configurations
    }
    rng = random.Random(seed)
    completed_runs = 0
    maximum_runs = len(all_configurations) * repetitions

    async def measure(configurations: list[tuple[int, int]], stage: str) -> None:
        nonlocal completed_runs
        for repetition in range(repetitions):
            round_order = configurations.copy()
            rng.shuffle(round_order)
            for batch_size, concurrency in round_order:
                if progress:
                    progress(
                        f"stage={stage} batch={batch_size} "
                        f"concurrency={concurrency} "
                        f"run={repetition + 1}/{repetitions}"
                    )
                measured_runs = await client.run_cell(
                    corpus,
                    batch_size=batch_size,
                    concurrency=concurrency,
                    duration_seconds=duration_seconds,
                    warmup_seconds=warmup_seconds,
                    repetitions=1,
                )
                measured_runs[0].repetition = repetition
                runs_by_configuration[(batch_size, concurrency)].extend(measured_runs)
                completed_runs += 1
                if checkpoint:
                    checkpoint(_measured_cells(runs_by_configuration), completed_runs, maximum_runs)

    if strategy == "grid":
        await measure(all_configurations, "grid")
    elif strategy == "adaptive":
        coarse = _coarse_configurations(
            sorted(set(batch_sizes)),
            sorted(set(concurrencies)),
            (baseline_batch, baseline_concurrency),
        )
        await measure(coarse, "coarse")
        coarse_cells = _measured_cells(runs_by_configuration)
        feasible_coarse = _feasible_cells(coarse_cells, constraints)
        ranked = sorted(
            feasible_coarse or coarse_cells,
            key=lambda cell: cell.throughput_texts_per_second,
            reverse=True,
        )[:3]
        refinement = _neighbor_configurations(
            ranked,
            sorted(set(batch_sizes)),
            sorted(set(concurrencies)),
        )
        missing = [
            configuration
            for configuration in refinement
            if not runs_by_configuration[configuration]
        ]
        if missing:
            await measure(missing, "refine")
    else:
        raise ValueError(f"unknown optimization strategy: {strategy}")

    cells = _measured_cells(runs_by_configuration)
    if checkpoint:
        checkpoint(cells, completed_runs, completed_runs)

    feasible = _feasible_cells(cells, constraints)
    recommended = choose_recommendation(feasible)
    baseline = next(
        (
            cell
            for cell in cells
            if cell.batch_size == baseline_batch
            and cell.concurrency == baseline_concurrency
        ),
        None,
    )
    return OptimizationResult(
        endpoint=client.base_url,
        server_info=server_info,
        corpus_summary=summarize_corpus(corpus),
        constraints=constraints,
        cells=cells,
        recommended=recommended,
        baseline=baseline,
        hourly_price=hourly_price,
        strategy=strategy,
        seed=seed,
    )


def choose_recommendation(feasible: list[CellResult]) -> CellResult | None:
    """Prefer lower concurrency only when near-peak estimates are indistinguishable."""
    if not feasible:
        return None
    peak = max(cell.throughput_texts_per_second for cell in feasible)
    if peak <= 0:
        return None
    peak_cell = max(feasible, key=lambda cell: cell.throughput_texts_per_second)
    peak_interval = peak_cell.throughput_confidence_interval
    near_peak = []
    for cell in feasible:
        within_three_percent = cell.throughput_texts_per_second >= peak * 0.97
        statistically_overlapping = _intervals_overlap(
            cell.throughput_confidence_interval, peak_interval
        )
        if cell is peak_cell or (within_three_percent and statistically_overlapping):
            near_peak.append(cell)
    return min(
        near_peak,
        key=lambda cell: (cell.concurrency, cell.p95_ms, cell.batch_size),
    )


def pareto_frontier(cells: list[CellResult]) -> list[CellResult]:
    """Return cells not dominated on both throughput and p95 latency."""
    frontier = []
    for candidate in cells:
        dominated = any(
            other is not candidate
            and other.throughput_texts_per_second
            >= candidate.throughput_texts_per_second
            and other.p95_ms <= candidate.p95_ms
            and (
                other.throughput_texts_per_second
                > candidate.throughput_texts_per_second
                or other.p95_ms < candidate.p95_ms
            )
            for other in cells
        )
        if not dominated:
            frontier.append(candidate)
    return sorted(frontier, key=lambda cell: cell.throughput_texts_per_second)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _intervals_overlap(
    first: tuple[float, float], second: tuple[float, float]
) -> bool:
    return max(first[0], second[0]) <= min(first[1], second[1])


def _measured_cells(
    runs_by_configuration: dict[tuple[int, int], list[RunResult]],
) -> list[CellResult]:
    return [
        CellResult(batch_size, concurrency, runs.copy())
        for (batch_size, concurrency), runs in sorted(runs_by_configuration.items())
        if runs
    ]


def _feasible_cells(
    cells: list[CellResult], constraints: Constraints
) -> list[CellResult]:
    return [
        cell
        for cell in cells
        if cell.satisfies(
            constraints.max_p95_ms,
            constraints.max_error_rate,
            constraints.min_successful_requests,
            constraints.max_throughput_cv,
        )
    ]


def _coarse_configurations(
    batch_sizes: list[int],
    concurrencies: list[int],
    baseline: tuple[int, int],
) -> list[tuple[int, int]]:
    def coarse_values(values: list[int]) -> list[int]:
        selected = values[::2]
        if values[-1] not in selected:
            selected.append(values[-1])
        return selected

    configurations = {
        (batch_size, concurrency)
        for batch_size in coarse_values(batch_sizes)
        for concurrency in coarse_values(concurrencies)
    }
    if baseline[0] in batch_sizes and baseline[1] in concurrencies:
        configurations.add(baseline)
    return sorted(configurations)


def _neighbor_configurations(
    cells: list[CellResult],
    batch_sizes: list[int],
    concurrencies: list[int],
) -> list[tuple[int, int]]:
    configurations: set[tuple[int, int]] = set()
    for cell in cells:
        batch_index = batch_sizes.index(cell.batch_size)
        concurrency_index = concurrencies.index(cell.concurrency)
        for batch_offset in (-1, 0, 1):
            for concurrency_offset in (-1, 0, 1):
                next_batch = batch_index + batch_offset
                next_concurrency = concurrency_index + concurrency_offset
                if 0 <= next_batch < len(batch_sizes) and 0 <= next_concurrency < len(
                    concurrencies
                ):
                    configurations.add(
                        (batch_sizes[next_batch], concurrencies[next_concurrency])
                    )
    return sorted(configurations)
