from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import sqrt
from statistics import mean, median, stdev
from typing import Any

from . import __version__


def percentile(values: list[float], quantile: float) -> float:
    """Return a linearly interpolated percentile without external dependencies."""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


@dataclass(frozen=True)
class WorkloadItem:
    text: str


@dataclass
class RunResult:
    batch_size: int
    concurrency: int
    repetition: int
    duration_seconds: float
    successful_requests: int
    failed_requests: int
    successful_texts: int
    compute_tokens: int
    latencies_ms: list[float] = field(repr=False)
    transport_latencies_ms: list[float] = field(default_factory=list, repr=False)
    decode_latencies_ms: list[float] = field(default_factory=list, repr=False)
    server_total_ms: list[float] = field(default_factory=list, repr=False)
    server_queue_ms: list[float] = field(default_factory=list, repr=False)
    server_tokenization_ms: list[float] = field(default_factory=list, repr=False)
    server_inference_ms: list[float] = field(default_factory=list, repr=False)
    client_cpu_seconds: float = 0.0
    offered_texts: int = 0
    scheduled_duration_seconds: float | None = None
    schedule_lag_ms: list[float] = field(default_factory=list, repr=False)
    status_counts: dict[str, int] = field(default_factory=dict)

    @property
    def requests(self) -> int:
        return self.successful_requests + self.failed_requests

    @property
    def throughput_texts_per_second(self) -> float:
        return self.successful_texts / self.duration_seconds

    @property
    def throughput_tokens_per_second(self) -> float | None:
        if self.compute_tokens <= 0:
            return None
        return self.compute_tokens / self.duration_seconds

    @property
    def error_rate(self) -> float:
        return self.failed_requests / self.requests if self.requests else 1.0

    @property
    def p50_ms(self) -> float:
        return percentile(self.latencies_ms, 0.50)

    @property
    def p95_ms(self) -> float:
        return percentile(self.latencies_ms, 0.95)

    @property
    def transport_p95_ms(self) -> float:
        return percentile(self.transport_latencies_ms, 0.95)

    @property
    def decode_p95_ms(self) -> float:
        return percentile(self.decode_latencies_ms, 0.95)

    @property
    def client_cpu_utilization(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return self.client_cpu_seconds / self.duration_seconds

    @property
    def offered_texts_per_second(self) -> float | None:
        if not self.scheduled_duration_seconds:
            return None
        return self.offered_texts / self.scheduled_duration_seconds

    @property
    def schedule_lag_p95_ms(self) -> float | None:
        return _optional_percentile(self.schedule_lag_ms, 0.95)

    @property
    def server_queue_p50_ms(self) -> float | None:
        return _optional_percentile(self.server_queue_ms, 0.50)

    @property
    def server_tokenization_p50_ms(self) -> float | None:
        return _optional_percentile(self.server_tokenization_ms, 0.50)

    @property
    def server_inference_p50_ms(self) -> float | None:
        return _optional_percentile(self.server_inference_ms, 0.50)

    @property
    def server_total_p50_ms(self) -> float | None:
        return _optional_percentile(self.server_total_ms, 0.50)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            throughput_texts_per_second=self.throughput_texts_per_second,
            throughput_tokens_per_second=self.throughput_tokens_per_second,
            error_rate=self.error_rate,
            p50_ms=self.p50_ms,
            p95_ms=self.p95_ms,
            transport_p95_ms=self.transport_p95_ms,
            decode_p95_ms=self.decode_p95_ms,
            client_cpu_utilization=self.client_cpu_utilization,
            offered_texts_per_second=self.offered_texts_per_second,
            schedule_lag_p95_ms=self.schedule_lag_p95_ms,
            server_queue_p50_ms=self.server_queue_p50_ms,
            server_tokenization_p50_ms=self.server_tokenization_p50_ms,
            server_inference_p50_ms=self.server_inference_p50_ms,
            server_total_p50_ms=self.server_total_p50_ms,
        )
        data.pop("latencies_ms")
        data.pop("transport_latencies_ms")
        data.pop("decode_latencies_ms")
        data.pop("server_total_ms")
        data.pop("server_queue_ms")
        data.pop("server_tokenization_ms")
        data.pop("server_inference_ms")
        data.pop("schedule_lag_ms")
        return data


@dataclass
class CellResult:
    batch_size: int
    concurrency: int
    runs: list[RunResult]

    @property
    def throughput_texts_per_second(self) -> float:
        return median(r.throughput_texts_per_second for r in self.runs)

    @property
    def mean_throughput_texts_per_second(self) -> float:
        return mean(r.throughput_texts_per_second for r in self.runs)

    @property
    def throughput_cv(self) -> float:
        values = [r.throughput_texts_per_second for r in self.runs]
        average = mean(values)
        if len(values) < 2 or average <= 0:
            return 0.0
        return stdev(values) / average

    @property
    def throughput_confidence_interval(self) -> tuple[float, float]:
        """Approximate 95% confidence interval using Student's t."""
        values = [r.throughput_texts_per_second for r in self.runs]
        average = mean(values)
        if len(values) < 2:
            return average, average
        critical = _t_critical_95(len(values) - 1)
        margin = critical * stdev(values) / sqrt(len(values))
        return max(0.0, average - margin), average + margin

    @property
    def throughput_tokens_per_second(self) -> float | None:
        values = [
            r.throughput_tokens_per_second
            for r in self.runs
            if r.throughput_tokens_per_second is not None
        ]
        return median(values) if values else None

    @property
    def p50_ms(self) -> float:
        return median(r.p50_ms for r in self.runs)

    @property
    def p95_ms(self) -> float:
        return median(r.p95_ms for r in self.runs)

    @property
    def worst_p95_ms(self) -> float:
        return max(r.p95_ms for r in self.runs)

    @property
    def transport_p95_ms(self) -> float:
        return median(r.transport_p95_ms for r in self.runs)

    @property
    def decode_p95_ms(self) -> float:
        return median(r.decode_p95_ms for r in self.runs)

    @property
    def error_rate(self) -> float:
        requests = sum(r.requests for r in self.runs)
        failures = sum(r.failed_requests for r in self.runs)
        return failures / requests if requests else 1.0

    @property
    def worst_error_rate(self) -> float:
        return max(r.error_rate for r in self.runs)

    @property
    def minimum_successful_requests(self) -> int:
        return min(r.successful_requests for r in self.runs)

    @property
    def client_cpu_utilization(self) -> float:
        return median(r.client_cpu_utilization for r in self.runs)

    @property
    def offered_texts_per_second(self) -> float | None:
        return _median_optional(r.offered_texts_per_second for r in self.runs)

    @property
    def schedule_lag_p95_ms(self) -> float | None:
        return _median_optional(r.schedule_lag_p95_ms for r in self.runs)

    @property
    def server_queue_p50_ms(self) -> float | None:
        return _median_optional(r.server_queue_p50_ms for r in self.runs)

    @property
    def server_tokenization_p50_ms(self) -> float | None:
        return _median_optional(r.server_tokenization_p50_ms for r in self.runs)

    @property
    def server_inference_p50_ms(self) -> float | None:
        return _median_optional(r.server_inference_p50_ms for r in self.runs)

    @property
    def server_total_p50_ms(self) -> float | None:
        return _median_optional(r.server_total_p50_ms for r in self.runs)

    def satisfies(
        self,
        max_p95_ms: float,
        max_error_rate: float,
        min_successful_requests: int = 1,
        max_throughput_cv: float = 1.0,
    ) -> bool:
        return (
            self.worst_p95_ms <= max_p95_ms
            and self.worst_error_rate <= max_error_rate
            and self.minimum_successful_requests >= min_successful_requests
            and self.throughput_cv <= max_throughput_cv
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_size": self.batch_size,
            "concurrency": self.concurrency,
            "throughput_texts_per_second": self.throughput_texts_per_second,
            "throughput_tokens_per_second": self.throughput_tokens_per_second,
            "mean_throughput_texts_per_second": self.mean_throughput_texts_per_second,
            "throughput_cv": self.throughput_cv,
            "throughput_confidence_interval": self.throughput_confidence_interval,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "worst_p95_ms": self.worst_p95_ms,
            "transport_p95_ms": self.transport_p95_ms,
            "decode_p95_ms": self.decode_p95_ms,
            "error_rate": self.error_rate,
            "worst_error_rate": self.worst_error_rate,
            "minimum_successful_requests": self.minimum_successful_requests,
            "client_cpu_utilization": self.client_cpu_utilization,
            "offered_texts_per_second": self.offered_texts_per_second,
            "schedule_lag_p95_ms": self.schedule_lag_p95_ms,
            "server_queue_p50_ms": self.server_queue_p50_ms,
            "server_tokenization_p50_ms": self.server_tokenization_p50_ms,
            "server_inference_p50_ms": self.server_inference_p50_ms,
            "server_total_p50_ms": self.server_total_p50_ms,
            "runs": [run.to_dict() for run in self.runs],
        }


@dataclass(frozen=True)
class Constraints:
    max_p95_ms: float
    max_error_rate: float
    min_successful_requests: int = 100
    max_throughput_cv: float = 0.10


@dataclass
class OptimizationResult:
    endpoint: str
    server_info: dict[str, Any]
    corpus_summary: dict[str, Any]
    constraints: Constraints
    cells: list[CellResult]
    recommended: CellResult | None
    baseline: CellResult | None
    hourly_price: float | None
    strategy: str = "grid"
    seed: int = 42
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "tool_version": __version__,
            "generated_at": self.generated_at,
            "endpoint": self.endpoint,
            "server_info": self.server_info,
            "corpus_summary": self.corpus_summary,
            "constraints": asdict(self.constraints),
            "recommended": self.recommended.to_dict() if self.recommended else None,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "hourly_price": self.hourly_price,
            "strategy": self.strategy,
            "seed": self.seed,
            "cells": [cell.to_dict() for cell in self.cells],
        }


@dataclass
class ValidationResult:
    endpoint: str
    server_info: dict[str, Any]
    corpus_summary: dict[str, Any]
    constraints: Constraints
    target_texts_per_second: float
    cell: CellResult
    passed: bool
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "tool_version": __version__,
            "generated_at": self.generated_at,
            "endpoint": self.endpoint,
            "server_info": self.server_info,
            "corpus_summary": self.corpus_summary,
            "constraints": asdict(self.constraints),
            "target_texts_per_second": self.target_texts_per_second,
            "passed": self.passed,
            "cell": self.cell.to_dict(),
        }


def _t_critical_95(degrees_of_freedom: int) -> float:
    values = {
        1: 12.706,
        2: 4.303,
        3: 3.182,
        4: 2.776,
        5: 2.571,
        6: 2.447,
        7: 2.365,
        8: 2.306,
        9: 2.262,
        10: 2.228,
        11: 2.201,
        12: 2.179,
        13: 2.160,
        14: 2.145,
        15: 2.131,
        16: 2.120,
        17: 2.110,
        18: 2.101,
        19: 2.093,
        20: 2.086,
        25: 2.060,
        30: 2.042,
    }
    if degrees_of_freedom in values:
        return values[degrees_of_freedom]
    if degrees_of_freedom < 25:
        return values[20]
    if degrees_of_freedom < 30:
        return values[25]
    return 1.96


def _optional_percentile(values: list[float], quantile: float) -> float | None:
    return percentile(values, quantile) if values else None


def _median_optional(values) -> float | None:
    present = [value for value in values if value is not None]
    return median(present) if present else None
