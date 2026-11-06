# Apple M1 Pro / bge-small case study

This is a local validation of TEI AutoTune against a real Hugging Face Text
Embeddings Inference server. It is evidence that the tool works end to end; it
is not a substitute for an NVIDIA production benchmark.

## Result

TEI AutoTune's adaptive search selected batch 1, concurrency 1 at 35.7 texts/s.
An exhaustive grid over concurrency 1, 2, and 4 selected batch 1, concurrency 2
at 35.4 texts/s. The adaptive result was within 1% of the grid's peak measured
throughput, although randomized run-to-run drift changed which of the two nearby
settings was selected.

Larger client batches reduced throughput on this Metal backend. Server timing
headers identified model inference as the dominant request cost. The grid's
recommended setting improved throughput by 9.5% over its batch 1, concurrency 1
baseline, while remaining below the 200 ms p95 latency constraint.

Fixed-arrival validation showed that saturated capacity is not a safe operating
rate:

| Offered load | Configuration | Achieved | p95 latency | Errors | Result |
|---:|---:|---:|---:|---:|:---:|
| 25 texts/s | batch 1, concurrency 2 | 25.0 texts/s | 65.2 ms | 0.00% | PASS |
| 32 texts/s | batch 1, concurrency 2 | 31.1 texts/s | 302.3 ms | 0.00% | FAIL |
| 37 texts/s | batch 1, concurrency 2 | 31.7 texts/s | 621.9 ms | 9.46% | FAIL |
| 32 texts/s | batch 1, concurrency 4 | 23.7 texts/s | 920.6 ms | 19.22% | FAIL |

The last experiment is important: client scheduling lag did not mean that more
concurrency would help. Raising concurrency made the overload worse. This led to
a diagnostic wording fix in TEI AutoTune so it reports observed waiting without
claiming that higher concurrency will increase endpoint capacity.

## Method

- TEI 1.9.3 installed from Homebrew, using the native Metal backend.
- Model: `BAAI/bge-small-en-v1.5`, float16.
- Corpus: 81 chunks derived from this repository's README and Python source;
  median 594 characters, p95 900 characters.
- Optimization: two repetitions, five measured seconds and one warmup second
  per configuration, randomized with seed 42.
- Validation: two repetitions of ten measured seconds plus one warmup second.
- Constraint: p95 latency at most 200 ms and error rate at most 1%.

These short runs are suitable for an integration case study, not a publishable
hardware comparison. A production study should use the target application's
corpus, longer measurement windows, at least three repetitions, and the actual
deployment hardware.

## Reproduce

Start TEI:

```bash
text-embeddings-router \
  --model-id BAAI/bge-small-en-v1.5 \
  --port 8080
```

The exact commands and host details are recorded in [environment.md](environment.md).
Generated reports and raw JSON are stored in the adjacent result directories.
