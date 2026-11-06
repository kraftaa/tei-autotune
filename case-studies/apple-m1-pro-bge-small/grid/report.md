# TEI AutoTune report

Endpoint: `http://127.0.0.1:8080`
Generated: `2026-11-06T18:46:34.756585+00:00`
Search strategy: `grid` (seed `42`)

## Recommendation

Use **batch size 1** with **2 in-flight requests**.

- Median throughput: 35.4 texts/s
- Median p95 latency: 85.8 ms
- Worst repeated-run p95: 86.6 ms
- Aggregate error rate: 0.00%
- Throughput coefficient of variation: 1.3%
- Client CPU utilization: 5.9% of one CPU core
- Median server-reported throughput: 6,659 tokens/s
- Improvement over tested baseline (batch 1, concurrency 1): +9.5%

The recommendation favors lower concurrency only when it is within 3% of the fastest feasible result and their approximate 95% throughput confidence intervals overlap.

Diagnostic: Model inference dominates the server-reported request time.

## Server

- Model: `BAAI/bge-small-en-v1.5`
- Model revision: `None`
- TEI version: `1.9.3`
- Maximum client batch size: `32`
- Maximum batch tokens: `16384`

## Workload

- Corpus items: 81
- Median characters per item: 594
- p95 characters per item: 900
- Maximum characters per item: 900

## Tested configurations

| Batch | Concurrency | Texts/s | Tokens/s | p95 ms | Decode p95 ms | Min requests | Throughput CV | Client CPU | Error rate | Pass |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 1 | 1 | 32.3 | 6,131 | 52.7 | 0.1 | 161 | 1.3% | 5.1% | 0.00% | yes |
| 1 | 2 | 35.4 | 6,659 | 85.8 | 0.1 | 177 | 1.3% | 5.9% | 0.00% | yes |
| 1 | 4 | 25.4 | 4,785 | 229.2 | 0.1 | 129 | 1.4% | 3.9% | 0.00% | no |
| 8 | 1 | 18.5 | 3,426 | 589.7 | 0.3 | 11 | 8.0% | 0.4% | 0.00% | no |
| 8 | 2 | 12.8 | 2,392 | 1,455.8 | 0.8 | 8 | 1.8% | 0.3% | 0.00% | no |
| 8 | 4 | 9.1 | 1,669 | 3,744.9 | 2.8 | 8 | 0.1% | 0.2% | 0.00% | no |
| 16 | 1 | 11.8 | 2,166 | 1,566.4 | 0.6 | 4 | 0.7% | 0.2% | 0.00% | no |
| 16 | 2 | 9.2 | 1,699 | 3,820.6 | 0.9 | 4 | 9.2% | 0.2% | 0.00% | no |
| 16 | 4 | 7.9 | 1,449 | 7,876.0 | 1.3 | 4 | 0.6% | 0.2% | 0.00% | no |
| 32 | 1 | 8.6 | 1,576 | 4,137.5 | 1.8 | 2 | 3.3% | 0.1% | 0.00% | no |
| 32 | 2 | 7.7 | 1,436 | 8,376.3 | 2.2 | 2 | 9.0% | 0.1% | 0.00% | no |
| 32 | 4 | 7.4 | 1,394 | 17,151.4 | 13.5 | 4 | 2.3% | 0.2% | 0.00% | no |

## Throughput/latency frontier

These configurations were not dominated by another tested configuration on both throughput and p95 latency.

- Batch 1, concurrency 1: 32.3 texts/s at 52.7 ms p95
- Batch 1, concurrency 2: 35.4 texts/s at 85.8 ms p95

## Interpretation limits

- This is a closed-loop endpoint capacity test. It does not reproduce an application's arrival pattern or prove that embedding is the application's bottleneck.
- End-to-end latency includes response-body transfer, JSON decoding, and response-shape validation.
- The baseline is the explicitly tested baseline configuration; it is not a measurement of the application's current behavior.
- Cost per million is theoretical saturated-capacity cost. An always-on instance's billed hourly cost does not fall merely because throughput rises.
- Results apply to this endpoint, corpus distribution, model, hardware, and test interval.
