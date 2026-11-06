# TEI AutoTune fixed-rate validation

Endpoint: `http://127.0.0.1:8080`
Generated: `2026-11-06T18:47:18.059711+00:00`

## PASS

- Configuration: batch 1, concurrency 2
- Target arrival rate: 25.0 texts/s
- Scheduled arrival rate: 25.0 texts/s
- Achieved throughput: 25.0 texts/s
- Median p95 end-to-end latency: 65.2 ms
- Worst repeated-run p95: 67.8 ms
- Error rate: 0.00%
- Throughput variation: 0.0%
- p95 client scheduling lag: 1.5 ms

Diagnostic: Model inference dominates the server-reported request time.

Latency begins at the scheduled arrival time, so it includes waiting for an available client concurrency slot, HTTP transfer, JSON decoding, and validation.
