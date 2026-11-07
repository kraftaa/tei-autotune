# TEI AutoTune

TEI AutoTune finds an efficient client batch size, concurrency, and safe arrival
rate for a Hugging Face Text Embeddings Inference (TEI) endpoint. It tests a
representative corpus, rejects configurations that violate latency or error
constraints, and produces a recommendation plus reproducible raw results.

The tool answers a deliberately narrow question: **which client-side operating
point makes good use of this existing endpoint for this workload?** It does not
change TEI configuration, modify the model, or claim that embedding is the
bottleneck in the surrounding application.

## Install

```bash
python -m pip install git+https://github.com/kraftaa/tei-autotune.git
```

## Quick start

Create `documents.txt` with one representative document or chunk per line, then
run one command:

```bash
tei-autotune run \
  --url http://localhost:8080 \
  --corpus documents.txt
```

TEI AutoTune will:

1. Find an efficient client batch size and concurrency.
2. Measure saturated endpoint capacity.
3. Ramp real arrival rates around that capacity.
4. Confirm the strongest passing boundary after cooldown.
5. Recommend a tested production rate with 10% headroom.

Results are written to `tei-autotune-results/`. Start with `summary.md`, then
open `safe-rate/rate-discovery.html` for the chart. The default profile is a
practical initial measurement. For longer three-repetition measurements, add
`--thorough`:

```bash
tei-autotune run \
  --url http://localhost:8080 \
  --corpus documents.txt \
  --thorough
```

For an authenticated endpoint, set `TEI_API_KEY`; the key is never written to
the result files.

## Advanced commands

The corpus may also use newline-delimited JSON. Each line can be a JSON string:

```jsonl
"First document to embed"
"A longer document representative of production traffic"
```

or an object containing a text field:

```jsonl
{"text": "First document to embed"}
{"text": "A longer document representative of production traffic"}
```

### Optimize an endpoint

Run only the client-configuration sweep:

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

Use `--api-key-env NAME` to read an API key from another environment variable.

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

### Discover a safe arrival rate

After selecting a batch size and concurrency, automatically ramp the fixed
arrival rate until the endpoint fails the constraints at two consecutive rates:

```bash
tei-autotune discover-rate \
  --url http://localhost:8080 \
  --corpus documents.jsonl \
  --batch-size 1 \
  --concurrency 2 \
  --min-rate 20 \
  --max-rate 40 \
  --step 1 \
  --failure-window 2 \
  --headroom 0.10 \
  --confirmation-cooldown 10 \
  --duration 60 \
  --repetitions 3 \
  --max-p95-ms 200 \
  --output rate-discovery/
```

The command tolerates an isolated failing rate because real measurements can be
non-monotonic, but stops after the configured number of consecutive failures.
It cools down and confirms the strongest ramp candidate with a fresh validation,
falling back to lower passing candidates when confirmation fails. The production
suggestion is an actually tested passing rate below the requested headroom, not
an interpolated number. Reports explain every failed constraint and include a
standalone HTML chart. `rate-discovery.partial.json` preserves completed ramp and
confirmation measurements if the command is interrupted.

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
