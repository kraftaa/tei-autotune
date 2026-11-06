from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx

from . import __version__
from .client import TeiClient
from .corpus import load_corpus
from .models import Constraints
from .optimizer import optimize
from .report import (
    write_checkpoint,
    write_outputs,
    write_rate_discovery_checkpoint,
    write_rate_discovery_outputs,
    write_validation_outputs,
)
from .validator import discover_safe_rate, validate_fixed_rate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tei-autotune",
        description=(
            "Find the highest-throughput TEI client configuration that satisfies "
            "latency and error-rate constraints."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    optimize_parser = subparsers.add_parser("optimize", help="run an optimization sweep")
    optimize_parser.add_argument("--url", required=True, help="TEI base URL")
    optimize_parser.add_argument("--corpus", required=True, type=Path, help="JSONL corpus")
    optimize_parser.add_argument(
        "--text-field", default="text", help="object field containing text"
    )
    optimize_parser.add_argument(
        "--batch-sizes", default="1,8,16,32", type=_positive_int_list
    )
    optimize_parser.add_argument(
        "--concurrency", default="1,2,4,8,16", type=_positive_int_list
    )
    optimize_parser.add_argument("--max-p95-ms", type=_positive_float, default=200.0)
    optimize_parser.add_argument(
        "--max-error-rate", type=_rate, default=0.01
    )
    optimize_parser.add_argument(
        "--min-requests",
        type=_positive_int,
        default=100,
        help="minimum successful requests required in every repeated run",
    )
    optimize_parser.add_argument(
        "--max-throughput-cv",
        type=_rate,
        default=0.10,
        help="maximum allowed throughput coefficient of variation",
    )
    optimize_parser.add_argument("--duration", type=_positive_float, default=10.0)
    optimize_parser.add_argument("--warmup", type=_nonnegative_float, default=2.0)
    optimize_parser.add_argument("--repetitions", type=_positive_int, default=3)
    optimize_parser.add_argument("--baseline-batch", type=_positive_int, default=1)
    optimize_parser.add_argument(
        "--baseline-concurrency", type=_positive_int, default=1
    )
    optimize_parser.add_argument("--hourly-price", type=_nonnegative_float)
    optimize_parser.add_argument("--timeout", type=_positive_float, default=120.0)
    optimize_parser.add_argument(
        "--seed", type=int, default=42, help="seed for randomized experiment order"
    )
    optimize_parser.add_argument(
        "--strategy",
        choices=("adaptive", "grid"),
        default="adaptive",
        help="adaptive samples a coarse grid and refines around leading results",
    )
    optimize_parser.add_argument(
        "--api-key-env",
        default="TEI_API_KEY",
        help="environment variable holding the TEI API key",
    )
    optimize_parser.add_argument("--output", type=Path, default=Path("results"))

    validate_parser = subparsers.add_parser(
        "validate", help="validate one configuration at a fixed text arrival rate"
    )
    validate_parser.add_argument("--url", required=True, help="TEI base URL")
    validate_parser.add_argument("--corpus", required=True, type=Path)
    validate_parser.add_argument("--text-field", default="text")
    validate_parser.add_argument("--batch-size", type=_positive_int, required=True)
    validate_parser.add_argument("--concurrency", type=_positive_int, required=True)
    validate_parser.add_argument(
        "--arrival-rate", type=_positive_float, required=True, help="offered texts/s"
    )
    validate_parser.add_argument("--max-p95-ms", type=_positive_float, default=200.0)
    validate_parser.add_argument("--max-error-rate", type=_rate, default=0.01)
    validate_parser.add_argument("--min-requests", type=_positive_int, default=100)
    validate_parser.add_argument("--max-throughput-cv", type=_rate, default=0.10)
    validate_parser.add_argument("--duration", type=_positive_float, default=60.0)
    validate_parser.add_argument("--warmup", type=_nonnegative_float, default=2.0)
    validate_parser.add_argument("--repetitions", type=_positive_int, default=3)
    validate_parser.add_argument("--timeout", type=_positive_float, default=120.0)
    validate_parser.add_argument("--api-key-env", default="TEI_API_KEY")
    validate_parser.add_argument(
        "--output", type=Path, default=Path("validation-results")
    )

    discover_parser = subparsers.add_parser(
        "discover-rate",
        help="find the highest fixed arrival rate that satisfies constraints",
    )
    discover_parser.add_argument("--url", required=True, help="TEI base URL")
    discover_parser.add_argument("--corpus", required=True, type=Path)
    discover_parser.add_argument("--text-field", default="text")
    discover_parser.add_argument("--batch-size", type=_positive_int, required=True)
    discover_parser.add_argument("--concurrency", type=_positive_int, required=True)
    discover_parser.add_argument("--min-rate", type=_positive_float, required=True)
    discover_parser.add_argument("--max-rate", type=_positive_float, required=True)
    discover_parser.add_argument("--step", type=_positive_float, default=1.0)
    discover_parser.add_argument(
        "--failure-window",
        type=_positive_int,
        default=2,
        help="stop after this many consecutive failing rates",
    )
    discover_parser.add_argument(
        "--headroom",
        type=_rate,
        default=0.10,
        help="production headroom below the confirmed boundary",
    )
    discover_parser.add_argument(
        "--confirmation-cooldown",
        type=_nonnegative_float,
        default=10.0,
        help="seconds to wait before confirming a boundary candidate",
    )
    discover_parser.add_argument(
        "--skip-confirmation",
        action="store_true",
        help="do not retest the highest passing rate after the ramp",
    )
    discover_parser.add_argument("--max-p95-ms", type=_positive_float, default=200.0)
    discover_parser.add_argument("--max-error-rate", type=_rate, default=0.01)
    discover_parser.add_argument("--min-requests", type=_positive_int, default=100)
    discover_parser.add_argument("--max-throughput-cv", type=_rate, default=0.10)
    discover_parser.add_argument("--duration", type=_positive_float, default=60.0)
    discover_parser.add_argument("--warmup", type=_nonnegative_float, default=2.0)
    discover_parser.add_argument("--repetitions", type=_positive_int, default=3)
    discover_parser.add_argument("--timeout", type=_positive_float, default=120.0)
    discover_parser.add_argument("--api-key-env", default="TEI_API_KEY")
    discover_parser.add_argument(
        "--output", type=Path, default=Path("rate-discovery-results")
    )
    return parser


async def run_optimize(args: argparse.Namespace) -> int:
    def progress(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    try:
        corpus = load_corpus(args.corpus, args.text_field)
        api_key = os.environ.get(args.api_key_env)
        client = TeiClient(args.url, timeout_seconds=args.timeout, api_key=api_key)
        constraints = Constraints(
            args.max_p95_ms,
            args.max_error_rate,
            args.min_requests,
            args.max_throughput_cv,
        )

        def checkpoint(cells, completed_runs, total_runs) -> None:
            write_checkpoint(
                endpoint=client.base_url,
                cells=cells,
                completed_runs=completed_runs,
                total_runs=total_runs,
                output_dir=args.output,
            )

        result = await optimize(
            client,
            corpus,
            batch_sizes=args.batch_sizes,
            concurrencies=args.concurrency,
            constraints=constraints,
            duration_seconds=args.duration,
            warmup_seconds=args.warmup,
            repetitions=args.repetitions,
            baseline_batch=args.baseline_batch,
            baseline_concurrency=args.baseline_concurrency,
            hourly_price=args.hourly_price,
            seed=args.seed,
            strategy=args.strategy,
            progress=progress,
            checkpoint=checkpoint,
        )
        json_path, report_path = write_outputs(result, args.output)
    except (httpx.HTTPError, OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if result.recommended:
        recommendation = result.recommended
        print(
            f"Recommended: batch={recommendation.batch_size} "
            f"concurrency={recommendation.concurrency} "
            f"throughput={recommendation.throughput_texts_per_second:.1f} texts/s "
            f"p95={recommendation.p95_ms:.1f} ms"
        )
    else:
        print("No tested configuration satisfied the constraints.")
    print(f"Report: {report_path}")
    print(f"Raw results: {json_path}")
    return 0


async def run_validate(args: argparse.Namespace) -> int:
    def progress(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    try:
        corpus = load_corpus(args.corpus, args.text_field)
        client = TeiClient(
            args.url,
            timeout_seconds=args.timeout,
            api_key=os.environ.get(args.api_key_env),
        )
        constraints = Constraints(
            args.max_p95_ms,
            args.max_error_rate,
            args.min_requests,
            args.max_throughput_cv,
        )
        result = await validate_fixed_rate(
            client,
            corpus,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
            arrival_rate_texts_per_second=args.arrival_rate,
            duration_seconds=args.duration,
            warmup_seconds=args.warmup,
            repetitions=args.repetitions,
            constraints=constraints,
            progress=progress,
        )
        json_path, report_path = write_validation_outputs(result, args.output)
    except (httpx.HTTPError, OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(
        f"{'PASS' if result.passed else 'FAIL'}: "
        f"throughput={result.cell.throughput_texts_per_second:.1f} texts/s "
        f"p95={result.cell.p95_ms:.1f} ms "
        f"errors={result.cell.error_rate:.2%}"
    )
    print(f"Report: {report_path}")
    print(f"Raw results: {json_path}")
    return 0 if result.passed else 1


async def run_discover_rate(args: argparse.Namespace) -> int:
    def progress(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    try:
        corpus = load_corpus(args.corpus, args.text_field)
        client = TeiClient(
            args.url,
            timeout_seconds=args.timeout,
            api_key=os.environ.get(args.api_key_env),
        )
        constraints = Constraints(
            args.max_p95_ms,
            args.max_error_rate,
            args.min_requests,
            args.max_throughput_cv,
        )
        result = await discover_safe_rate(
            client,
            corpus,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
            min_rate=args.min_rate,
            max_rate=args.max_rate,
            step=args.step,
            failure_window=args.failure_window,
            headroom=args.headroom,
            confirm=not args.skip_confirmation,
            confirmation_cooldown_seconds=args.confirmation_cooldown,
            duration_seconds=args.duration,
            warmup_seconds=args.warmup,
            repetitions=args.repetitions,
            constraints=constraints,
            progress=progress,
            checkpoint=lambda validations, confirmations: write_rate_discovery_checkpoint(
                validations, confirmations, args.output
            ),
        )
        json_path, report_path = write_rate_discovery_outputs(result, args.output)
    except (httpx.HTTPError, OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if result.recommended is None:
        if result.ramp_recommended is None:
            print("No ramp rate satisfied the constraints.")
        else:
            print("No ramp candidate passed fresh confirmation.")
    else:
        label = (
            "Confirmed maximum"
            if result.confirmation_enabled
            else "Highest passing rate"
        )
        print(
            f"{label}: "
            f"{result.recommended.target_texts_per_second:g} texts/s"
        )
        if result.production_rate is not None:
            print(f"Suggested production rate: {result.production_rate:g} texts/s")
        elif result.headroom > 0:
            print("No tested passing rate provides the requested production headroom.")
    if result.non_monotonic:
        print("Warning: observed a passing rate above a lower failing rate.")
    print(f"Report: {report_path}")
    print(f"HTML: {args.output / 'rate-discovery.html'}")
    print(f"Raw results: {json_path}")
    return 0 if result.recommended is not None else 1


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "optimize":
        try:
            exit_code = asyncio.run(run_optimize(args))
        except KeyboardInterrupt:
            print(
                f"interrupted; partial results may be available in "
                f"{args.output / 'results.partial.json'}",
                file=sys.stderr,
            )
            exit_code = 130
        raise SystemExit(exit_code)
    if args.command == "validate":
        try:
            exit_code = asyncio.run(run_validate(args))
        except KeyboardInterrupt:
            print("validation interrupted", file=sys.stderr)
            exit_code = 130
        raise SystemExit(exit_code)
    if args.command == "discover-rate":
        try:
            exit_code = asyncio.run(run_discover_rate(args))
        except KeyboardInterrupt:
            print(
                f"rate discovery interrupted; partial results may be available in "
                f"{args.output / 'rate-discovery.partial.json'}",
                file=sys.stderr,
            )
            exit_code = 130
        raise SystemExit(exit_code)


def _positive_int_list(value: str) -> list[int]:
    try:
        values = [int(part.strip()) for part in value.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected comma-separated integers") from error
    if not values or any(item <= 0 for item in values):
        raise argparse.ArgumentTypeError("all values must be positive integers")
    return values


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return parsed


def _rate(value: str) -> float:
    parsed = float(value)
    if not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return parsed
