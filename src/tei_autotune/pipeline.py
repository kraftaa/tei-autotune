from __future__ import annotations

import json
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Callable

from .client import TeiClient
from .models import Constraints, OptimizationResult, RateDiscoveryResult, WorkloadItem
from .optimizer import optimize
from .report import (
    write_checkpoint,
    write_outputs,
    write_rate_discovery_checkpoint,
    write_rate_discovery_outputs,
)
from .validator import discover_safe_rate


@dataclass(frozen=True)
class RunProfile:
    optimization_duration: float
    validation_duration: float
    warmup: float
    repetitions: int
    confirmation_cooldown: float


QUICK_PROFILE = RunProfile(5, 15, 2, 2, 5)
THOROUGH_PROFILE = RunProfile(10, 60, 5, 3, 10)


def derive_rate_plan(capacity: float) -> tuple[float, float, float]:
    """Create a compact ramp spanning 50% to 110% of measured capacity."""
    if capacity <= 0:
        raise ValueError("measured capacity must be positive")
    step = max(1.0, round(capacity * 0.10, 1))
    minimum = max(step, ceil(capacity * 0.50 / step) * step)
    maximum = ceil(capacity * 1.10 / step) * step
    return round(minimum, 10), round(maximum, 10), round(step, 10)


async def run_pipeline(
    client: TeiClient,
    corpus: list[WorkloadItem],
    *,
    constraints: Constraints,
    headroom: float,
    thorough: bool,
    output_dir: Path,
    progress: Callable[[str], None] | None = None,
) -> tuple[OptimizationResult, RateDiscoveryResult | None]:
    profile = THOROUGH_PROFILE if thorough else QUICK_PROFILE
    optimization_dir = output_dir / "optimization"
    rate_dir = output_dir / "safe-rate"

    if progress:
        progress("Step 1/2: optimizing batch size and concurrency")
    optimization = await optimize(
        client,
        corpus,
        batch_sizes=[1, 8, 16, 32],
        concurrencies=[1, 2, 4, 8, 16],
        constraints=constraints,
        duration_seconds=profile.optimization_duration,
        warmup_seconds=profile.warmup,
        repetitions=profile.repetitions,
        baseline_batch=1,
        baseline_concurrency=1,
        hourly_price=None,
        seed=42,
        strategy="adaptive",
        progress=progress,
        checkpoint=lambda cells, completed, total: write_checkpoint(
            endpoint=client.base_url,
            cells=cells,
            completed_runs=completed,
            total_runs=total,
            output_dir=optimization_dir,
        ),
    )
    write_outputs(optimization, optimization_dir)
    if optimization.recommended is None:
        write_run_summary(optimization, None, output_dir, thorough)
        return optimization, None

    recommendation = optimization.recommended
    minimum, maximum, step = derive_rate_plan(
        recommendation.throughput_texts_per_second
    )
    if progress:
        progress(
            "Step 2/2: discovering safe arrival rate "
            f"from {minimum:g} to {maximum:g} texts/s"
        )
    discovery = await discover_safe_rate(
        client,
        corpus,
        batch_size=recommendation.batch_size,
        concurrency=recommendation.concurrency,
        min_rate=minimum,
        max_rate=maximum,
        step=step,
        failure_window=2,
        headroom=headroom,
        confirm=True,
        confirmation_cooldown_seconds=profile.confirmation_cooldown,
        duration_seconds=profile.validation_duration,
        warmup_seconds=profile.warmup,
        repetitions=profile.repetitions,
        constraints=constraints,
        progress=progress,
        checkpoint=lambda validations, confirmations: write_rate_discovery_checkpoint(
            validations, confirmations, rate_dir
        ),
    )
    write_rate_discovery_outputs(discovery, rate_dir)
    write_run_summary(optimization, discovery, output_dir, thorough)
    return optimization, discovery


def write_run_summary(
    optimization: OptimizationResult,
    discovery: RateDiscoveryResult | None,
    output_dir: Path,
    thorough: bool,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.md"
    json_path = output_dir / "summary.json"
    recommendation = optimization.recommended
    lines = [
        "# TEI AutoTune summary",
        "",
        f"Profile: `{'thorough' if thorough else 'quick'}`",
        "",
    ]
    if recommendation is None:
        lines.extend(
            [
                "No client configuration satisfied the latency, error, sample, and stability constraints.",
                "",
                "See [the optimization report](optimization/report.md) for details.",
            ]
        )
    else:
        lines.extend(
            [
                "## Recommended client settings",
                "",
                f"- Batch size: **{recommendation.batch_size}**",
                f"- Concurrency: **{recommendation.concurrency}**",
                f"- Saturated throughput: {recommendation.throughput_texts_per_second:.1f} texts/s",
                "",
            ]
        )
        if discovery and discovery.recommended:
            lines.extend(
                [
                    "## Safe arrival rate",
                    "",
                    f"- Confirmed boundary: **{discovery.recommended.target_texts_per_second:g} texts/s**",
                    (
                        f"- Suggested production rate: **{discovery.production_rate:g} texts/s**"
                        if discovery.production_rate is not None
                        else "- No tested passing rate provides the requested headroom"
                    ),
                    "",
                    "Open [the HTML rate report](safe-rate/rate-discovery.html) for the capacity chart.",
                ]
            )
        else:
            lines.extend(
                [
                    "No arrival-rate candidate passed fresh confirmation.",
                    "See [the safe-rate report](safe-rate/rate-discovery.md) for details.",
                ]
            )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "profile": "thorough" if thorough else "quick",
                "batch_size": recommendation.batch_size if recommendation else None,
                "concurrency": recommendation.concurrency if recommendation else None,
                "saturated_throughput": (
                    recommendation.throughput_texts_per_second
                    if recommendation
                    else None
                ),
                "confirmed_rate": (
                    discovery.recommended.target_texts_per_second
                    if discovery and discovery.recommended
                    else None
                ),
                "production_rate": discovery.production_rate if discovery else None,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return summary_path, json_path
