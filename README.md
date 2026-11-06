# TEI AutoTune

TEI AutoTune finds an efficient client batch size and request concurrency for a
Hugging Face Text Embeddings Inference (TEI) endpoint. It tests a representative
JSONL corpus, rejects configurations that violate latency or error constraints,
and produces a recommendation plus reproducible raw results.

The tool answers a deliberately narrow question: **which client-side operating
point makes good use of this existing endpoint for this workload?** It does not
change TEI configuration, modify the model, or claim that embedding is the
bottleneck in the surrounding application.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Optimize an endpoint

The corpus may contain JSON strings:

```jsonl
"First document to embed"
"A longer document representative of production traffic"
```

or objects containing a text field:

```jsonl
{"text": "First document to embed"}
{"text": "A longer document representative of production traffic"}
```

Run a sweep:

```bash
tei-autotune optimize \
  --url http://localhost:8080 \
  --corpus documents.jsonl \
  --max-p95-ms 200 \
  --max-error-rate 0.01 \
  --min-requests 100 \
  --max-throughput-cv 0.10 \
  --batch-sizes 1,8,16,32 \
  --concurrency 1,2,4,8,16 \
  --strategy adaptive \
  --hourly-price 0.70 \
  --output results/
```

For an authenticated endpoint, set `TEI_API_KEY`; the key is never written to
the result files. Use `--api-key-env NAME` to read another environment variable.

Outputs:

- `report.md` contains the recommendation, complete result matrix, efficient
  throughput/latency frontier, and interpretation limits.
- `results.json` contains server metadata and per-run measurements for later
  analysis.
- `results.partial.json` is atomically updated after every measured run, so an
  interrupted sweep retains its completed measurements.

TEI AutoTune reads `/info` when available and removes batch sizes above the
server's `max_client_batch_size`. It uses the `/embed` endpoint and performs a
closed-loop capacity test. Each worker sends another request after its previous
request completes. End-to-end latency includes response transfer, JSON decoding,
and response-shape validation.

## Recommendation policy

A configuration is feasible only when every repeated run satisfies the maximum
p95 latency, error-rate, minimum-request, and throughput-stability constraints.
Experiment order is randomized and interleaved across repetitions with a
reproducible seed. Among feasible configurations within 3% of peak throughput,
TEI AutoTune selects lower concurrency only when the configurations' approximate
95% throughput confidence intervals overlap. This favors a simpler production
setting without treating ordinary measurement noise as a real improvement.

The reported baseline defaults to batch 1 and concurrency 1. It is a tested
reference point, not a measurement of the application's existing behavior. Set
`--baseline-batch` and `--baseline-concurrency` to another tested pair when that
better represents the current client.

When TEI returns `x-compute-tokens`, the report includes exact server-reported
token throughput. Character distribution is always recorded because text count
alone can hide major workload differences. The report also separates transport
and JSON-decoding latency and warns when the load generator approaches full use
of one CPU core.

When TEI supplies its standard timing headers, the report records queue,
tokenization, inference, and total server time. The recommendation uses those
measurements to explain whether the observed limit is most consistent with
client CPU, client concurrency, TEI queueing, tokenization, or model inference.

### Adaptive search

`--strategy adaptive` is the default. It measures a coarse grid that includes
the boundaries and requested baseline, ranks the feasible candidates, then
measures neighboring configurations around the three leading results. Use
`--strategy grid` to exhaustively test every requested combination.

### Validate production arrival rate

After optimization, validate one configuration under a fixed offered arrival
rate:

```bash
tei-autotune validate \
  --url http://localhost:8080 \
  --corpus documents.jsonl \
  --batch-size 8 \
  --concurrency 6 \
  --arrival-rate 1000 \
  --duration 120 \
  --max-p95-ms 200 \
  --output validation-results/
```

Validation schedules requests independently of response completion. Its latency
starts at the intended arrival time, so client-side waiting for a concurrency
slot is visible. A bounded queue prevents an overloaded validation run from
exhausting client memory; arrivals rejected by that queue count as errors.

## Important limits

- Capacity testing adds load. Run it against an endpoint where the selected
  concurrency and batch sizes are acceptable.
- Closed-loop saturation results do not reproduce an application's real arrival
  process or prove that TEI is the end-to-end bottleneck.
- Cost per million texts is saturated-capacity cost derived from a user-supplied
  hourly price. Higher throughput does not reduce the bill for an instance that
  remains online for the same number of hours.
- Results apply to the tested model, hardware, corpus, endpoint configuration,
  and test interval.
- `--seed` controls randomized experiment order; its default is `42`.

## Case study

The [Apple M1 Pro / bge-small case study](case-studies/apple-m1-pro-bge-small/README.md)
runs adaptive optimization, an exhaustive low-concurrency grid, and fixed-rate
validation against a real TEI 1.9.3 server. It also documents a negative result:
larger batches and additional concurrency reduced performance on that Metal
backend.

## Development

```bash
pip install -e '.[dev]'
pytest
```
