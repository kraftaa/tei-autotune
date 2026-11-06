# TEI AutoTune fixed-rate validation

Endpoint: `http://127.0.0.1:8080`
Generated: `2026-11-06T18:47:49.238132+00:00`

## FAIL

- Configuration: batch 1, concurrency 2
- Target arrival rate: 32.0 texts/s
- Scheduled arrival rate: 32.0 texts/s
- Achieved throughput: 31.1 texts/s
- Median p95 end-to-end latency: 302.3 ms
- Worst repeated-run p95: 473.8 ms
- Error rate: 0.00%
- Throughput variation: 3.3%
- p95 client scheduling lag: 238.5 ms

Diagnostic: The offered load exceeds what this configuration can serve promptly; requests spend substantial time waiting for a client slot. Scheduling lag alone does not show that higher concurrency will increase capacity.

Latency begins at the scheduled arrival time, so it includes waiting for an available client concurrency slot, HTTP transfer, JSON decoding, and validation.
