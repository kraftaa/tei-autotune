# TEI AutoTune report

Endpoint: `http://127.0.0.1:8080`
Generated: `2026-11-06T18:40:48.190520+00:00`
Search strategy: `adaptive` (seed `42`)

## Recommendation

Use **batch size 1** with **1 in-flight requests**.

- Median throughput: 35.7 texts/s
- Median p95 latency: 46.2 ms
- Worst repeated-run p95: 46.9 ms
- Aggregate error rate: 0.00%
- Throughput coefficient of variation: 0.9%
- Client CPU utilization: 4.7% of one CPU core
- Median server-reported throughput: 6,715 tokens/s
- Improvement over tested baseline (batch 1, concurrency 1): +0.0%

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
| 1 | 1 | 35.7 | 6,715 | 46.2 | 0.1 | 178 | 0.9% | 4.7% | 0.00% | yes |
| 1 | 2 | 34.7 | 6,527 | 87.4 | 0.1 | 175 | 1.0% | 6.2% | 0.00% | yes |
| 1 | 4 | 27.3 | 5,103 | 212.0 | 0.1 | 138 | 0.0% | 3.4% | 0.00% | no |
| 1 | 16 | 13.4 | 2,501 | 1,512.1 | 0.1 | 82 | 7.5% | 2.1% | 0.00% | no |
| 8 | 1 | 17.7 | 3,279 | 611.2 | 0.5 | 11 | 5.5% | 0.5% | 0.00% | no |
| 8 | 2 | 12.9 | 2,422 | 1,518.2 | 0.4 | 9 | 0.7% | 0.3% | 0.00% | no |
| 16 | 1 | 13.8 | 2,607 | 1,279.6 | 0.7 | 5 | 0.5% | 0.2% | 0.00% | no |
| 16 | 4 | 8.5 | 1,566 | 7,518.3 | 0.6 | 4 | 4.7% | 0.1% | 0.00% | no |
| 16 | 16 | 7.8 | 1,475 | 32,782.4 | 0.8 | 16 | 4.9% | 0.2% | 0.00% | no |
| 32 | 1 | 9.1 | 1,670 | 3,834.7 | 1.3 | 2 | 0.3% | 0.1% | 0.00% | no |
| 32 | 4 | 8.4 | 1,576 | 14,992.8 | 1.2 | 4 | 2.9% | 0.1% | 0.00% | no |
| 32 | 16 | 7.7 | 1,450 | 66,746.2 | 1.8 | 16 | 0.6% | 0.1% | 0.00% | no |

## Throughput/latency frontier

These configurations were not dominated by another tested configuration on both throughput and p95 latency.

- Batch 1, concurrency 1: 35.7 texts/s at 46.2 ms p95

## Interpretation limits

- This is a closed-loop endpoint capacity test. It does not reproduce an application's arrival pattern or prove that embedding is the application's bottleneck.
- End-to-end latency includes response-body transfer, JSON decoding, and response-shape validation.
- The baseline is the explicitly tested baseline configuration; it is not a measurement of the application's current behavior.
- Cost per million is theoretical saturated-capacity cost. An always-on instance's billed hourly cost does not fall merely because throughput rises.
- Results apply to this endpoint, corpus distribution, model, hardware, and test interval.
