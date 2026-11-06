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
