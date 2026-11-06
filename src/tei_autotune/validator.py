from __future__ import annotations

import asyncio
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
    headroom: float,
    confirm: bool,
    confirmation_cooldown_seconds: float,
    duration_seconds: float,
    warmup_seconds: float,
    repetitions: int,
    constraints: Constraints,
    progress: Callable[[str], None] | None = None,
    checkpoint: (
        Callable[[list[ValidationResult], list[ValidationResult]], None] | None
    ) = None,
) -> RateDiscoveryResult:
    if max_rate < min_rate:
        raise ValueError("maximum rate must be greater than or equal to minimum rate")
    if step <= 0:
        raise ValueError("rate step must be positive")
    if failure_window <= 0:
        raise ValueError("failure window must be positive")
    if not 0 <= headroom < 1:
        raise ValueError("headroom must be between 0 and 1")
    if confirmation_cooldown_seconds < 0:
        raise ValueError("confirmation cooldown must be nonnegative")

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
            checkpoint(validations, [])
        if consecutive_failures >= failure_window:
            break
        index += 1

    passing = sorted(
        (item for item in validations if item.passed),
        key=lambda item: item.target_texts_per_second,
        reverse=True,
    )
    ramp_recommended = passing[0] if passing else None
    confirmations: list[ValidationResult] = []
    recommended = None
    if confirm:
        for candidate in passing:
            if confirmation_cooldown_seconds:
                if progress:
                    progress(
                        f"confirmation cooldown={confirmation_cooldown_seconds:g}s"
                    )
                await asyncio.sleep(confirmation_cooldown_seconds)
            if progress:
                progress(
                    f"confirming offered={candidate.target_texts_per_second:g} texts/s"
                )
            confirmation = await validate_fixed_rate(
                client,
                corpus,
                batch_size=batch_size,
                concurrency=concurrency,
                arrival_rate_texts_per_second=candidate.target_texts_per_second,
                duration_seconds=duration_seconds,
                warmup_seconds=warmup_seconds,
                repetitions=repetitions,
                constraints=constraints,
                progress=progress,
            )
            confirmations.append(confirmation)
            if checkpoint:
                checkpoint(validations, confirmations)
            if confirmation.passed:
                recommended = confirmation
                break
    else:
        recommended = ramp_recommended

    production_rate = None
    if recommended is not None:
        headroom_limit = recommended.target_texts_per_second * (1 - headroom)
        headroom_candidates = [
            item.target_texts_per_second
            for item in passing
            if item.target_texts_per_second <= headroom_limit + 1e-9
        ]
        if headroom_candidates:
            production_rate = max(headroom_candidates)
        elif headroom == 0:
            production_rate = recommended.target_texts_per_second

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
        headroom=headroom,
        confirmation_enabled=confirm,
        confirmation_cooldown_seconds=confirmation_cooldown_seconds,
        validations=validations,
        confirmations=confirmations,
        ramp_recommended=ramp_recommended,
        recommended=recommended,
        production_rate=production_rate,
        stopped_early=last_rate < max_rate - 1e-9,
        non_monotonic=non_monotonic,
    )
