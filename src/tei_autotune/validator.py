from __future__ import annotations

from typing import Callable

from .client import TeiClient
from .corpus import summarize_corpus
from .models import (
    CellResult,
    Constraints,
    RateDiscoveryResult,
    ValidationResult,
    WorkloadItem,
)


async def validate_fixed_rate(
    client: TeiClient,
    corpus: list[WorkloadItem],
    *,
    batch_size: int,
    concurrency: int,
    arrival_rate_texts_per_second: float,
    duration_seconds: float,
    warmup_seconds: float,
    repetitions: int,
    constraints: Constraints,
    progress: Callable[[str], None] | None = None,
) -> ValidationResult:
    server_info = await client.get_info()
    max_batch = server_info.get("max_client_batch_size")
    if isinstance(max_batch, int) and batch_size > max_batch:
        raise ValueError(
            f"batch size {batch_size} exceeds server maximum {max_batch}"
        )
    await client.check_embed(corpus[0].text)

    runs = []
    for repetition in range(repetitions):
        if progress:
            progress(f"fixed-rate validation run={repetition + 1}/{repetitions}")
        runs.append(
            await client.run_open_loop(
                corpus,
                batch_size=batch_size,
                concurrency=concurrency,
                arrival_rate_texts_per_second=arrival_rate_texts_per_second,
                duration_seconds=duration_seconds,
                warmup_seconds=warmup_seconds,
                repetition=repetition,
            )
        )
    cell = CellResult(batch_size, concurrency, runs)
    passed = cell.satisfies(
        constraints.max_p95_ms,
        constraints.max_error_rate,
        constraints.min_successful_requests,
        constraints.max_throughput_cv,
    )
    return ValidationResult(
        endpoint=client.base_url,
        server_info=server_info,
        corpus_summary=summarize_corpus(corpus),
        constraints=constraints,
        target_texts_per_second=arrival_rate_texts_per_second,
        cell=cell,
        passed=passed,
    )


async def discover_safe_rate(
    client: TeiClient,
    corpus: list[WorkloadItem],
    *,
    batch_size: int,
    concurrency: int,
    min_rate: float,
    max_rate: float,
    step: float,
    failure_window: int,
    duration_seconds: float,
    warmup_seconds: float,
    repetitions: int,
    constraints: Constraints,
    progress: Callable[[str], None] | None = None,
    checkpoint: Callable[[list[ValidationResult]], None] | None = None,
) -> RateDiscoveryResult:
    if max_rate < min_rate:
        raise ValueError("maximum rate must be greater than or equal to minimum rate")
    if step <= 0:
        raise ValueError("rate step must be positive")
    if failure_window <= 0:
        raise ValueError("failure window must be positive")

    validations: list[ValidationResult] = []
    consecutive_failures = 0
    saw_failure = False
    non_monotonic = False
    index = 0

    while True:
        rate = round(min_rate + index * step, 10)
        if rate > max_rate + 1e-9:
            break
        if progress:
            progress(f"rate discovery offered={rate:g} texts/s")
        validation = await validate_fixed_rate(
            client,
            corpus,
            batch_size=batch_size,
            concurrency=concurrency,
            arrival_rate_texts_per_second=rate,
            duration_seconds=duration_seconds,
            warmup_seconds=warmup_seconds,
            repetitions=repetitions,
            constraints=constraints,
            progress=progress,
        )
        validations.append(validation)
        if validation.passed:
            non_monotonic = non_monotonic or saw_failure
            consecutive_failures = 0
        else:
            saw_failure = True
            consecutive_failures += 1
        if checkpoint:
            checkpoint(validations)
        if consecutive_failures >= failure_window:
            break
        index += 1

    passing = [item for item in validations if item.passed]
    recommended = max(
        passing,
        key=lambda item: item.target_texts_per_second,
        default=None,
    )
    last_rate = validations[-1].target_texts_per_second
    return RateDiscoveryResult(
        endpoint=validations[0].endpoint,
        server_info=validations[0].server_info,
        corpus_summary=validations[0].corpus_summary,
        constraints=constraints,
        batch_size=batch_size,
        concurrency=concurrency,
        min_rate=min_rate,
        max_rate=max_rate,
        step=step,
        failure_window=failure_window,
        validations=validations,
        recommended=recommended,
        stopped_early=last_rate < max_rate - 1e-9,
        non_monotonic=non_monotonic,
    )
