import json

import pytest

from tei_autotune.corpus import load_corpus, summarize_corpus


def test_loads_string_and_object_jsonl(tmp_path):
    path = tmp_path / "corpus.jsonl"
    path.write_text(
        '\n'.join([json.dumps("one"), json.dumps({"body": "three"})]),
        encoding="utf-8",
    )

    items = load_corpus(path, text_field="body")

    assert [item.text for item in items] == ["one", "three"]
    assert summarize_corpus(items)["characters_total"] == 8


def test_rejects_missing_text_field(tmp_path):
    path = tmp_path / "corpus.jsonl"
    path.write_text('{"wrong":"field"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="string field 'text'"):
        load_corpus(path)

