# Changelog

## 0.5.1 - 2026-11-07

- Start automatic safe-rate ramps at 40% of saturated capacity so a confirmed
  low boundary still has a tested candidate available for production headroom.
- Add reproducible Kubernetes benchmark overlays for NVIDIA A10G, L4, and L40S
  hardware.

## 0.5.0 - 2026-11-06

- Add `tei-autotune run`, a one-command workflow that optimizes client settings,
  derives an arrival-rate ramp, confirms the safe boundary, and writes one
  summary.
- Accept plain text corpora with one document per line in addition to JSONL.
- Add quick defaults and an optional `--thorough` profile.

## 0.4.0 - 2026-11-06

- Confirm the strongest safe-rate candidate with a fresh validation after a
  configurable cooldown, falling back to lower ramp candidates when needed.
- Recommend production headroom only from rates that were actually tested and
  passed.
- Explain the exact latency, error, sample-count, or stability constraint behind
  every failed validation.
- Generate a standalone HTML safe-rate report with a latency-boundary chart.
- Preserve both ramp and confirmation measurements in interrupted-run
  checkpoints.

## 0.3.0 - 2026-11-06

- Add sequential safe-arrival-rate discovery with configurable steps and early
  stopping after consecutive failures.
- Detect and report non-monotonic pass/fail results.
- Save JSON, Markdown, and partial checkpoint outputs.

## 0.2.0 - 2026-11-06

- Add adaptive client-configuration search, repeated measurements, confidence
  intervals, fixed-rate validation, and diagnostic timing analysis.
- Add the Apple M1 Pro and `bge-small-en-v1.5` case study.
