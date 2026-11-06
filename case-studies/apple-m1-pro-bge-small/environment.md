# Environment and commands

- Host: MacBook Pro 2021 (`MacBookPro18,1`)
- Chip: Apple M1 Pro, 10 CPU cores and 16 GPU cores
- Memory: 32 GB
- TEI: 1.9.3 from Homebrew
- Backend: Metal
- Model: `BAAI/bge-small-en-v1.5`, float16
- TEI limits: 512 input tokens, 16,384 batch tokens, client batch size 32
- TEI server command: `text-embeddings-router --model-id BAAI/bge-small-en-v1.5 --port 8080`

Optimization used the common arguments below:

```bash
tei-autotune optimize \
  --url http://127.0.0.1:8080 \
  --corpus case-studies/apple-m1-pro-bge-small/corpus.jsonl \
  --batch-sizes 1,8,16,32 \
  --max-p95-ms 200 \
  --max-error-rate 0.01 \
  --max-throughput-cv 0.15 \
  --duration 5 \
  --warmup 1 \
  --repetitions 2 \
  --seed 42
```

The adaptive run used concurrency `1,2,4,8,16`, `--min-requests 20`, and
`--strategy adaptive`. The grid run used concurrency `1,2,4`,
`--min-requests 2`, and `--strategy grid`. The lower minimum was necessary
because slow large-batch configurations completed fewer than 20 requests in a
five-second window; this is one reason the study is described as exploratory.

Fixed-rate validation used batch 1, concurrency 2, two ten-second repetitions,
one warmup second, and arrival rates 25, 32, and 37 texts/s. A diagnostic follow-up
repeated 32 texts/s at concurrency 4.
