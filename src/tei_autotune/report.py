from __future__ import annotations

import json
from html import escape
from pathlib import Path

from . import __version__
from .models import (
    CellResult,
    OptimizationResult,
    RateDiscoveryResult,
    ValidationResult,
)
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


def write_rate_discovery_outputs(
    result: RateDiscoveryResult, output_dir: Path
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "rate-discovery.json"
    report_path = output_dir / "rate-discovery.md"
    html_path = output_dir / "rate-discovery.html"
    json_path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_rate_discovery_markdown(result), encoding="utf-8")
    html_path.write_text(render_rate_discovery_html(result), encoding="utf-8")
    (output_dir / "rate-discovery.partial.json").unlink(missing_ok=True)
    return json_path, report_path


def write_rate_discovery_checkpoint(
    validations: list[ValidationResult],
    confirmations: list[ValidationResult],
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "rate-discovery.partial.json"
    temporary = output_dir / "rate-discovery.partial.json.tmp"
    temporary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tool_version": __version__,
                "status": "in_progress",
                "validations": [item.to_dict() for item in validations],
                "confirmations": [item.to_dict() for item in confirmations],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


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
    ]
    failures = cell.failure_reasons(result.constraints)
    if failures:
        lines.extend(["", "Failed constraints:"])
        lines.extend(f"- {reason}" for reason in failures)
    lines.extend(
        [
            "",
            f"Diagnostic: {_diagnose_cell(cell)}",
            "",
            "Latency begins at the scheduled arrival time, so it includes waiting for an available client concurrency slot, HTTP transfer, JSON decoding, and validation.",
            "",
        ]
    )
    return "\n".join(lines)


def render_rate_discovery_markdown(result: RateDiscoveryResult) -> str:
    lines = [
        "# TEI AutoTune safe-rate discovery",
        "",
        f"Endpoint: `{result.endpoint}`",
        f"Generated: `{result.generated_at}`",
        f"Configuration: batch {result.batch_size}, concurrency {result.concurrency}",
        "",
        "## Recommendation",
        "",
    ]
    if result.recommended is None:
        if result.ramp_recommended is None:
            lines.append("No ramp rate satisfied all constraints.")
        else:
            lines.append(
                "At least one ramp rate passed, but no boundary candidate passed fresh confirmation."
            )
    else:
        cell = result.recommended.cell
        label = "confirmed" if result.confirmation_enabled else "passing tested"
        lines.extend(
            [
                f"The highest {label} rate is **{result.recommended.target_texts_per_second:g} texts/s** for this configuration.",
                "",
                f"- Achieved throughput: {cell.throughput_texts_per_second:,.1f} texts/s",
                f"- Median p95 latency: {cell.p95_ms:,.1f} ms",
                f"- Worst repeated-run p95: {cell.worst_p95_ms:,.1f} ms",
                f"- Aggregate error rate: {cell.error_rate:.2%}",
            ]
        )
        if result.production_rate is not None:
            lines.append(
                f"- Suggested production rate with {result.headroom:.0%} headroom: **{result.production_rate:g} texts/s**"
            )
        elif result.headroom > 0:
            lines.append(
                f"- No tested passing rate provides the requested {result.headroom:.0%} headroom"
            )
    if result.non_monotonic:
        lines.extend(
            [
                "",
                "Warning: a higher tested rate passed after a lower rate failed. Treat the boundary as noisy and repeat it before production use.",
            ]
        )
    lines.extend(
        [
            "",
            "## Tested rates",
            "",
            "| Offered | Achieved | Median p95 | Worst p95 | Errors | Scheduling lag p95 | Result | Failed constraints |",
            "|---:|---:|---:|---:|---:|---:|:---:|:---|",
        ]
    )
    for validation in result.validations:
        cell = validation.cell
        lag = (
            f"{cell.schedule_lag_p95_ms:,.1f} ms"
            if cell.schedule_lag_p95_ms is not None
            else "n/a"
        )
        lines.append(
            f"| {validation.target_texts_per_second:g}/s | "
            f"{cell.throughput_texts_per_second:,.1f}/s | {cell.p95_ms:,.1f} ms | "
            f"{cell.worst_p95_ms:,.1f} ms | {cell.error_rate:.2%} | {lag} | "
            f"{'PASS' if validation.passed else 'FAIL'} | "
            f"{'; '.join(cell.failure_reasons(result.constraints)) or '—'} |"
        )
    if result.confirmations:
        lines.extend(["", "## Boundary confirmation", ""])
        for confirmation in result.confirmations:
            reasons = "; ".join(
                confirmation.cell.failure_reasons(result.constraints)
            )
            lines.append(
                f"- {confirmation.target_texts_per_second:g} texts/s: "
                f"{'PASS' if confirmation.passed else 'FAIL'}"
                + (f" — {reasons}" if reasons else "")
            )
    lines.extend(
        [
            "",
            f"The ramp stopped after {result.failure_window} consecutive failing rates."
            if result.stopped_early
            else "The ramp reached the configured maximum rate.",
            "A passing result applies only to this workload, endpoint, and test interval.",
            "",
        ]
    )
    return "\n".join(lines)


def render_rate_discovery_html(result: RateDiscoveryResult) -> str:
    validations = result.validations
    rates = [item.target_texts_per_second for item in validations]
    latencies = [item.cell.worst_p95_ms for item in validations]
    width, height, pad = 820, 340, 58
    min_rate, max_rate = min(rates), max(rates)
    max_latency = max(max(latencies), result.constraints.max_p95_ms) * 1.1

    def x(value: float) -> float:
        span = max(max_rate - min_rate, 1.0)
        return pad + (value - min_rate) / span * (width - 2 * pad)

    def y(value: float) -> float:
        return height - pad - value / max_latency * (height - 2 * pad)

    points = " ".join(
        f'{x(rate):.1f},{y(latency):.1f}'
        for rate, latency in zip(rates, latencies)
    )
    circles = "".join(
        f'<circle cx="{x(item.target_texts_per_second):.1f}" '
        f'cy="{y(item.cell.worst_p95_ms):.1f}" r="6" '
        f'fill="{"#16803c" if item.passed else "#c83232"}"><title>'
        f'{item.target_texts_per_second:g}/s: {item.cell.worst_p95_ms:.1f} ms'
        f'</title></circle>'
        for item in validations
    )
    rows = []
    for item in validations:
        reasons = "; ".join(item.cell.failure_reasons(result.constraints)) or "—"
        rows.append(
            "<tr>"
            f"<td>{item.target_texts_per_second:g}/s</td>"
            f"<td>{item.cell.throughput_texts_per_second:.1f}/s</td>"
            f"<td>{item.cell.p95_ms:.1f} ms</td>"
            f"<td>{item.cell.worst_p95_ms:.1f} ms</td>"
            f"<td>{item.cell.error_rate:.2%}</td>"
            f'<td class="{"pass" if item.passed else "fail"}">'
            f'{"PASS" if item.passed else "FAIL"}</td>'
            f"<td>{escape(reasons)}</td>"
            "</tr>"
        )
    recommendation = (
        f"Confirmed maximum: {result.recommended.target_texts_per_second:g} texts/s"
        if result.recommended is not None and result.confirmation_enabled
        else (
            f"Highest passing rate: {result.recommended.target_texts_per_second:g} texts/s"
            if result.recommended is not None
            else "No confirmed safe rate"
        )
    )
    production = (
        f"Suggested production rate: {result.production_rate:g} texts/s"
        if result.production_rate is not None
        else "No tested rate provides the requested headroom"
    )
    threshold_y = y(result.constraints.max_p95_ms)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TEI AutoTune safe-rate discovery</title>
<style>body{{font:16px system-ui;max-width:1040px;margin:40px auto;padding:0 20px;color:#18202a}}h1{{margin-bottom:4px}}.cards{{display:flex;gap:16px;flex-wrap:wrap}}.card{{background:#f4f6f8;border-radius:10px;padding:16px 20px;font-weight:650}}svg{{width:100%;height:auto;background:#fbfcfd;border:1px solid #d9dee5;border-radius:10px}}table{{border-collapse:collapse;width:100%}}th,td{{padding:9px;border-bottom:1px solid #d9dee5;text-align:left}}.pass{{color:#16803c;font-weight:700}}.fail{{color:#c83232;font-weight:700}}small{{color:#586576}}</style></head>
<body><h1>TEI AutoTune safe-rate discovery</h1><small>{escape(result.endpoint)} · batch {result.batch_size}, concurrency {result.concurrency}</small>
<div class="cards"><div class="card">{escape(recommendation)}</div><div class="card">{escape(production)}</div></div>
<h2>Worst repeated-run p95 latency</h2>
<svg viewBox="0 0 {width} {height}" role="img" aria-label="Worst p95 latency by offered rate">
<line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#718096"/><line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height-pad}" stroke="#718096"/>
<line x1="{pad}" y1="{threshold_y:.1f}" x2="{width-pad}" y2="{threshold_y:.1f}" stroke="#d08b00" stroke-dasharray="7 5"/><text x="{pad+6}" y="{threshold_y-7:.1f}" fill="#8a5b00">{result.constraints.max_p95_ms:g} ms limit</text>
<polyline points="{points}" fill="none" stroke="#4263eb" stroke-width="3"/>{circles}
<text x="{width/2:.0f}" y="{height-12}" text-anchor="middle">Offered texts/s</text><text x="16" y="{height/2:.0f}" transform="rotate(-90 16 {height/2:.0f})" text-anchor="middle">Worst p95 ms</text></svg>
<h2>Measurements</h2><table><thead><tr><th>Offered</th><th>Achieved</th><th>Median p95</th><th>Worst p95</th><th>Errors</th><th>Result</th><th>Failed constraints</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</body></html>"""


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
