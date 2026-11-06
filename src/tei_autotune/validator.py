from __future__ import annotations

from typing import Callable

from .client import TeiClient
from .corpus import summarize_corpus
from .models import (
    CellResult,
    Constraints,
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
