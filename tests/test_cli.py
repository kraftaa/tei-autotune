import asyncio

from tei_autotune.cli import build_parser, run_optimize


def test_missing_corpus_returns_clean_error(tmp_path, capsys):
    args = build_parser().parse_args(
        [
            "optimize",
            "--url",
            "http://mock-tei",
            "--corpus",
            str(tmp_path / "missing.jsonl"),
        ]
    )

    exit_code = asyncio.run(run_optimize(args))

    assert exit_code == 2
    assert "error:" in capsys.readouterr().err


def test_discover_rate_parser():
    args = build_parser().parse_args(
        [
            "discover-rate",
            "--url",
            "http://mock-tei",
            "--corpus",
            "corpus.jsonl",
            "--batch-size",
            "1",
            "--concurrency",
            "2",
            "--min-rate",
            "20",
            "--max-rate",
            "40",
        ]
    )

    assert args.step == 1
    assert args.failure_window == 2
    assert args.headroom == 0.10
    assert args.confirmation_cooldown == 10
    assert not args.skip_confirmation


def test_simple_run_parser_needs_only_url_and_corpus():
    args = build_parser().parse_args(
        [
            "run",
            "--url",
            "http://mock-tei",
            "--corpus",
            "documents.txt",
        ]
    )

    assert args.max_p95_ms == 200
    assert args.headroom == 0.10
    assert not args.thorough
    assert str(args.output) == "tei-autotune-results"
