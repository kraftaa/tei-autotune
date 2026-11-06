# TEI AutoTune fixed-rate validation

Endpoint: `http://127.0.0.1:8080`
Generated: `2026-11-06T18:48:22.337684+00:00`

## FAIL

- Configuration: batch 1, concurrency 2
- Target arrival rate: 37.0 texts/s
- Scheduled arrival rate: 37.0 texts/s
- Achieved throughput: 31.7 texts/s
- Median p95 end-to-end latency: 621.9 ms
- Worst repeated-run p95: 642.3 ms
- Error rate: 9.46%
- Throughput variation: 1.5%
- p95 client scheduling lag: 553.9 ms

Diagnostic: The offered load exceeds what this configuration can serve promptly; requests spend substantial time waiting for a client slot. Scheduling lag alone does not show that higher concurrency will increase capacity.

Latency begins at the scheduled arrival time, so it includes waiting for an available client concurrency slot, HTTP transfer, JSON decoding, and validation.
