from __future__ import annotations

import json
from pathlib import Path
from statistics import median

from .models import WorkloadItem, percentile


def load_corpus(path: Path, text_field: str = "text") -> list[WorkloadItem]:
    """Load newline-delimited JSON strings or objects containing a text field."""
    items: list[WorkloadItem] = []
    with path.open(encoding="utf-8") as corpus_file:
        for line_number, raw_line in enumerate(corpus_file, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"{path}:{line_number}: expected valid JSONL: {error.msg}"
                ) from error

            if isinstance(value, str):
                text = value
            elif isinstance(value, dict) and isinstance(value.get(text_field), str):
                text = value[text_field]
            else:
                raise ValueError(
                    f"{path}:{line_number}: expected a JSON string or an object "
                    f"with string field {text_field!r}"
                )
            if text:
                items.append(WorkloadItem(text=text))

    if not items:
        raise ValueError(f"{path}: corpus contains no non-empty texts")
    return items


def summarize_corpus(items: list[WorkloadItem]) -> dict[str, int | float]:
    lengths = [len(item.text) for item in items]
    return {
        "items": len(items),
        "characters_total": sum(lengths),
        "characters_min": min(lengths),
        "characters_median": median(lengths),
        "characters_p95": percentile([float(v) for v in lengths], 0.95),
        "characters_max": max(lengths),
    }
