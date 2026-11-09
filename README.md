# semantic-metrics-agent-kit

An agent answers "what was revenue?" with a number nobody can check — this kit makes every answer carry its definition, version, and provenance, and refuses uncertified / wrong-grain asks.

## Problem

Agents and dashboards routinely invent metric definitions, mix versions, or answer a weekly question from daily data without saying so. The number looks confident and is unverifiable.

## What this kit does

- **Certified registry (`metrics.json`, not YAML)** — 8 certified metrics over fictional Helios Home daily rows: `revenue` (v2), `orders`, `conversion_rate`, `avg_order_value`, `refund_rate`, `support_tickets`, `active_users`, `gross_margin`. Each entry carries a formula description, a structured aggregation spec (sum / mean / ratio with numerator and denominator fields), grain `daily`, unit, owner, status `certified`, and supported dimensions. The registry also contains a draft `churn_rate`, a deprecated metric, and `revenue` v1 superseded by v2 on a different field — so misuse is testable, not hypothetical.
- **Strict query contract** — structured request only: `{metric, grain, filters, window, version?}`. No natural-language parsing. Validation happens first; the engine never best-guesses.
- **Typed refusals** — `UNKNOWN_METRIC`, `UNCERTIFIED_METRIC`, `DEPRECATED_METRIC`, `SUPERSEDED_VERSION`, `GRAIN_MISMATCH`, `FILTER_ERROR` (unknown dimension or value-type conflict), `DIMENSION_MISMATCH` (a known dimension the metric does not support).
- **Provenance on every valid answer** — definition id, version, sha256 hash of the canonical filter JSON, source row count after filters, and certification status, alongside the value.
- **In-memory aggregation** — no SQL engine. A deterministic seeded generator (seed 42, 90 days, 12 channel/region rows per day) is shared by the CLI and the evals.
- **Misuse evals** — one case per misuse class plus valid requests whose values are recomputed independently in the eval. Refusal precision, refusal recall, and correct-answer rate on valid requests are reported separately — never as one blended accuracy.

## Quickstart

```bash
python3 -m semantic_metrics.cli list
python3 -m semantic_metrics.cli ask --request '{"metric":"revenue","grain":"daily","filters":{"channel":"online"},"window":{"start":"2026-01-01","end":"2026-01-31"}}'
python3 -m semantic_metrics.cli check   # CI gate: exit 0 ok, 1 registry invalid, 2 registry unreadable
python3 -m semantic_metrics.cli demo
python3 demo.py                         # end-to-end, including serve round-trip
python3 -m semantic_metrics.cli serve --port 8765   # POST /ask, GET /health on 127.0.0.1
python3 evals/run_evals.py
python3 -m unittest discover -s tests -v
```

## Design decisions (validated)

1. **JSON registry over YAML** — stdlib `json` parses it with zero dependencies; a YAML registry would need a third-party parser and break the stdlib-only rule.
2. **Validation before aggregation, with typed errors** — callers (and evals) can branch on a stable error code instead of parsing prose, and a refusal is provably not a computed answer.
3. **Filter hash from canonical JSON** — sorting keys and using compact separators makes the provenance hash stable regardless of how the caller ordered the filter dict; this is covered by a dedicated test.

## Scope limits (honest)

- Fictional Helios Home data only; no real business data, no external APIs, no network calls.
- Daily grain only — weekly/monthly asks are refused by design, not rolled up.
- Python standard library only. No SQL engine, no natural-language parsing, no automatic metric discovery.
- Single-process, in-memory: not a production semantic layer, warehouse, or serving system.

## Layout

```
metrics.json                  certified registry
semantic_metrics/data.py      deterministic generator (seed 42)
semantic_metrics/registry.py  registry loading
semantic_metrics/engine.py    contract validation + aggregation + provenance
semantic_metrics/cli.py       list / ask / check / demo / serve
evals/run_evals.py            misuse + valid evals -> evals/eval_report.json
tests/test_engine.py          hermetic unittest suite (incl. no-network guard)
demo.py                       end-to-end demo incl. serve round-trip
```

## License

MIT — see `LICENSE`. Copyright Akash Bhargava.
