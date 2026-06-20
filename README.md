# Orchestrator SDK

A polyglot SDK to orchestrate **multi-agent workflows** from a declarative template.
You describe a use case as tasks (some parallel, some sequential); the SDK autonomously
runs the right agents + tools, with **concurrency**, **rate limiting**, and optional **LLM**
reasoning, then returns a **summary report** (per-task timing, critical decisions, output).

## Layout

| Path | What |
|---|---|
| [DESIGN.md](DESIGN.md) | Full architecture & design (read this first). |
| [spec/spec.schema.json](spec/spec.schema.json) | The workflow template schema — single source of truth. |
| [spec/examples/](spec/examples/) | Sample workflows (`market-analysis.{yaml,json}`). |
| [proto/orchestrator.proto](proto/orchestrator.proto) | gRPC contract between the Go engine and thin clients. |
| [sdk-python/](sdk-python/) | **Python reference implementation** — runs workflows today; semantics oracle. |

## Architecture (decided)

Shared **Go** orchestration engine + thin native clients (Python, Java, JS/TS) over gRPC.
The engine owns scheduling, concurrency, rate limiting and the report; clients author specs
and run skill handlers in-process via a skill-dispatch stream. See [DESIGN.md](DESIGN.md).

The Python package is the reference engine: it runs in-process (no Go required) and defines
the canonical scheduling + report semantics the Go engine and other SDKs must match.

## Try it

```bash
cd sdk-python
python3 examples/run_market.py   # runs the market-analysis workflow, fully offline
python3 tests/test_engine.py     # behavioral tests: parallelism, rate limit, retries, fail-fast
```

## Status

- [x] Workflow spec schema + parser + DAG validation
- [x] gRPC contract (proto)
- [x] Reference engine: DAG scheduler, concurrency pool, global + per-provider rate limiting,
      retries/timeout/cancellation, fail-fast/continue, report + critical path
- [x] LLM provider interface (Mock + Anthropic adapter)
- [ ] Go engine + Redis durable state (Service mode, resumable runs)
- [ ] JS/TS + Java SDKs (built against the conformance suite)
- [ ] `foreach` dynamic fan-out (v1.1)
