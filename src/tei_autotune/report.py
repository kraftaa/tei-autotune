from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from .models import CellResult, OptimizationResult, ValidationResult
from .optimizer import pareto_frontier


def write_outputs(result: OptimizationResult, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "results.json"
    report_path = output_dir / "report.md"
    json_path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path, report_path


def write_checkpoint(
    *,
    endpoint: str,
    cells: list[CellResult],
    completed_runs: int,
    total_runs: int,
    output_dir: Path,
) -> Path:
    """Atomically preserve partial measurements during a long sweep."""
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / "results.partial.json"
    temporary_path = output_dir / "results.partial.json.tmp"
    data = {
        "schema_version": 1,
        "tool_version": __version__,
        "status": "complete" if completed_runs == total_runs else "in_progress",
        "endpoint": endpoint,
        "completed_runs": completed_runs,
        "total_runs": total_runs,
        "cells": [cell.to_dict() for cell in cells],
    }
    temporary_path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary_path.replace(checkpoint_path)
    return checkpoint_path


def write_validation_outputs(
    result: ValidationResult, output_dir: Path
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "validation.json"
    report_path = output_dir / "validation.md"
    json_path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_validation_markdown(result), encoding="utf-8")
    return json_path, report_path


def render_markdown(result: OptimizationResult) -> str:
    lines = [
        "# TEI AutoTune report",
        "",
        f"Endpoint: `{result.endpoint}`",
        f"Generated: `{result.generated_at}`",
        f"Search strategy: `{result.strategy}` (seed `{result.seed}`)",
        "",
        "## Recommendation",
        "",
    ]
    recommended = result.recommended
    if recommended is None:
        lines.extend(
            [
                "No tested configuration satisfied both constraints:",
                "",
                f"- Maximum p95 latency: {result.constraints.max_p95_ms:.1f} ms",
                f"- Maximum error rate: {result.constraints.max_error_rate:.2%}",
                f"- Minimum successful requests per run: {result.constraints.min_successful_requests}",
                f"- Maximum throughput variation: {result.constraints.max_throughput_cv:.1%}",
                "",
                "Review the complete matrix before relaxing a constraint or changing the server.",
            ]
        )
    else:
        lines.extend(_recommendation(result, recommended))

    lines.extend(
        [
            "",
            "## Server",
            "",
            f"- Model: `{result.server_info.get('model_id', 'not reported')}`",
            f"- Model revision: `{result.server_info.get('model_sha', 'not reported')}`",
            f"- TEI version: `{result.server_info.get('version', 'not reported')}`",
            f"- Maximum client batch size: `{result.server_info.get('max_client_batch_size', 'not reported')}`",
            f"- Maximum batch tokens: `{result.server_info.get('max_batch_tokens', 'not reported')}`",
            "",
            "## Workload",
            "",
            f"- Corpus items: {result.corpus_summary['items']}",
            f"- Median characters per item: {result.corpus_summary['characters_median']:.0f}",
            f"- p95 characters per item: {result.corpus_summary['characters_p95']:.0f}",
            f"- Maximum characters per item: {result.corpus_summary['characters_max']}",
            "",
            "## Tested configurations",
            "",
            "| Batch | Concurrency | Texts/s | Tokens/s | p95 ms | Decode p95 ms | Min requests | Throughput CV | Client CPU | Error rate | Pass |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
        ]
    )
    for cell in sorted(result.cells, key=lambda item: (item.batch_size, item.concurrency)):
        tokens = (
            f"{cell.throughput_tokens_per_second:,.0f}"
            if cell.throughput_tokens_per_second is not None
            else "n/a"
        )
        passes = cell.satisfies(
            result.constraints.max_p95_ms,
            result.constraints.max_error_rate,
            result.constraints.min_successful_requests,
            result.constraints.max_throughput_cv,
        )
        lines.append(
            f"| {cell.batch_size} | {cell.concurrency} | "
            f"{cell.throughput_texts_per_second:,.1f} | {tokens} | "
            f"{cell.p95_ms:,.1f} | {cell.decode_p95_ms:,.1f} | "
            f"{cell.minimum_successful_requests} | {cell.throughput_cv:.1%} | "
            f"{cell.client_cpu_utilization:.1%} | {cell.error_rate:.2%} | "
            f"{'yes' if passes else 'no'} |"
        )

    frontier = pareto_frontier(result.cells)
    lines.extend(
        [
            "",
            "## Throughput/latency frontier",
            "",
            "These configurations were not dominated by another tested configuration on both throughput and p95 latency.",
            "",
        ]
    )
    for cell in frontier:
        lines.append(
            f"- Batch {cell.batch_size}, concurrency {cell.concurrency}: "
            f"{cell.throughput_texts_per_second:,.1f} texts/s at "
            f"{cell.p95_ms:,.1f} ms p95"
        )

    lines.extend(
        [
            "",
            "## Interpretation limits",
            "",
            "- This is a closed-loop endpoint capacity test. It does not reproduce an application's arrival pattern or prove that embedding is the application's bottleneck.",
            "- End-to-end latency includes response-body transfer, JSON decoding, and response-shape validation.",
            "- The baseline is the explicitly tested baseline configuration; it is not a measurement of the application's current behavior.",
            "- Cost per million is theoretical saturated-capacity cost. An always-on instance's billed hourly cost does not fall merely because throughput rises.",
            "- Results apply to this endpoint, corpus distribution, model, hardware, and test interval.",
            "",
        ]
    )
    return "\n".join(lines)


def _recommendation(
    result: OptimizationResult, recommended: CellResult
) -> list[str]:
    lines = [
        f"Use **batch size {recommended.batch_size}** with "
        f"**{recommended.concurrency} in-flight requests**.",
        "",
        f"- Median throughput: {recommended.throughput_texts_per_second:,.1f} texts/s",
        f"- Median p95 latency: {recommended.p95_ms:,.1f} ms",
        f"- Worst repeated-run p95: {recommended.worst_p95_ms:,.1f} ms",
        f"- Aggregate error rate: {recommended.error_rate:.2%}",
        f"- Throughput coefficient of variation: {recommended.throughput_cv:.1%}",
        f"- Client CPU utilization: {recommended.client_cpu_utilization:.1%} of one CPU core",
    ]
    if recommended.throughput_tokens_per_second is not None:
        lines.append(
            f"- Median server-reported throughput: "
            f"{recommended.throughput_tokens_per_second:,.0f} tokens/s"
        )
    baseline = result.baseline
    if baseline and baseline.throughput_texts_per_second > 0:
        improvement = (
            recommended.throughput_texts_per_second
            / baseline.throughput_texts_per_second
            - 1
        )
        lines.append(
            f"- Improvement over tested baseline (batch {baseline.batch_size}, "
            f"concurrency {baseline.concurrency}): {improvement:+.1%}"
        )
    if result.hourly_price is not None:
        cost = (
            result.hourly_price
            * 1_000_000
            / (recommended.throughput_texts_per_second * 3600)
        )
        lines.append(
            f"- Theoretical saturated-capacity cost: ${cost:,.4f} per million texts"
        )
    lines.extend(
        [
            "",
            "The recommendation favors lower concurrency only when it is within 3% of the fastest feasible result and their approximate 95% throughput confidence intervals overlap.",
        ]
    )
    if recommended.client_cpu_utilization >= 0.85:
        lines.extend(
            [
                "",
                "Warning: the load generator used at least 85% of one CPU core. Client-side work may be limiting the measured endpoint throughput.",
            ]
        )
    lines.extend(["", f"Diagnostic: {_diagnose_cell(recommended)}"])
    return lines


def render_validation_markdown(result: ValidationResult) -> str:
    cell = result.cell
    offered = cell.offered_texts_per_second or result.target_texts_per_second
    lag = cell.schedule_lag_p95_ms
    lines = [
        "# TEI AutoTune fixed-rate validation",
        "",
        f"Endpoint: `{result.endpoint}`",
        f"Generated: `{result.generated_at}`",
        "",
        f"## {'PASS' if result.passed else 'FAIL'}",
        "",
        f"- Configuration: batch {cell.batch_size}, concurrency {cell.concurrency}",
        f"- Target arrival rate: {result.target_texts_per_second:,.1f} texts/s",
        f"- Scheduled arrival rate: {offered:,.1f} texts/s",
        f"- Achieved throughput: {cell.throughput_texts_per_second:,.1f} texts/s",
        f"- Median p95 end-to-end latency: {cell.p95_ms:,.1f} ms",
        f"- Worst repeated-run p95: {cell.worst_p95_ms:,.1f} ms",
        f"- Error rate: {cell.error_rate:.2%}",
        f"- Throughput variation: {cell.throughput_cv:.1%}",
        f"- p95 client scheduling lag: {lag:,.1f} ms" if lag is not None else "- p95 client scheduling lag: n/a",
        "",
        f"Diagnostic: {_diagnose_cell(cell)}",
        "",
        "Latency begins at the scheduled arrival time, so it includes waiting for an available client concurrency slot, HTTP transfer, JSON decoding, and validation.",
        "",
    ]
    return "\n".join(lines)


def _diagnose_cell(cell: CellResult) -> str:
    if cell.client_cpu_utilization >= 0.85:
        return "The load-generator process is near one full CPU core; client work may limit throughput."
    if cell.schedule_lag_p95_ms is not None and cell.schedule_lag_p95_ms > cell.p95_ms * 0.25:
        return (
            "The offered load exceeds what this configuration can serve promptly; "
            "requests spend substantial time waiting for a client slot. Scheduling "
            "lag alone does not show that higher concurrency will increase capacity."
        )
    queue = cell.server_queue_p50_ms
    inference = cell.server_inference_p50_ms
    tokenization = cell.server_tokenization_p50_ms
    if queue is not None and inference is not None and queue > inference:
        return "TEI queue time exceeds inference time, indicating saturation or excessive offered load."
    if inference is not None and tokenization is not None and inference > tokenization * 2:
        return "Model inference dominates the server-reported request time."
    if tokenization is not None and inference is not None and tokenization > inference:
        return "Server-side tokenization exceeds inference time for this workload."
    return "No dominant bottleneck could be identified from the available timing data."
