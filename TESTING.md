# Local Testing Guide

How to verify every layer of the SDK: Go engine unit tests, Python reference SDK tests,
and the full end-to-end contract between them.

Prerequisites: **Go 1.21+** and **Python 3.9+** (both standard library only — no `pip install`
needed for any test here).

---

## 1. Go engine — unit tests

Tests cover spec parsing, DAG validation, template resolution, rate limiting,
report / critical-path, and the scheduler (parallelism, retries, fail-fast, etc.).

```bash
cd /Users/manikandankasi/Desktop/mani/dev/orchestrator/engine

go test ./...
```

Expected output:
```
ok  github.com/org/orchestrator/internal/ratelimit
ok  github.com/org/orchestrator/internal/report
ok  github.com/org/orchestrator/internal/scheduler
ok  github.com/org/orchestrator/internal/spec
```

Run a specific package with verbose output:

```bash
go test -v ./internal/scheduler/...
go test -v ./internal/spec/...
go test -v ./internal/ratelimit/...
go test -v ./internal/report/...
```

Run with the race detector (catches any concurrency bugs):

```bash
go test -race ./...
```

---

## 2. Build the engine binary

```bash
cd /Users/manikandankasi/Desktop/mani/dev/orchestrator/engine

go build -o orchestrator ./cmd/orchestrator
ls -lh orchestrator   # should be ~3–4 MB
```

---

## 3. Smoke-test the binary directly (NDJSON protocol)

Send a minimal workflow via stdin and inspect stdout:

```bash
echo '{"type":"start_run","spec_json":"{\"workflow\":{\"name\":\"smoke\",\"tasks\":[{\"id\":\"a\",\"skill\":\"s\"}]}}","inputs_json":"{}"}' \
  | ./orchestrator
```

The engine will:
1. Print `{"type":"run_accepted","run_id":"r_..."}` 
2. Print `{"type":"event","event_type":"task.started",...}`
3. Print `{"type":"skill_invocation","invocation_id":"...","skill":"s",...}` — then wait for a result

Because you haven't sent a `skill_result`, it will hang (the engine is correctly waiting for your client). Use `Ctrl-C` to exit. This confirms the binary speaks the protocol.

---

## 4. Python reference SDK — unit tests

Tests the in-process Python engine: parallelism, concurrency limit, rate-limit throttling,
retries, fail-fast, continue-on-error, cycle rejection.

```bash
cd /Users/manikandankasi/Desktop/mani/dev/orchestrator/sdk-python

python3 tests/test_engine.py
```

Expected output:
```
running 7 tests

- test_concurrency_limit_serializes
  max_parallel=1 serialized 2x150ms into 302ms (OK)
- test_continue_on_error_isolates_branch
  continue: failed branch isolated, independent task c succeeded (OK)
- test_cycle_rejected
  cyclic spec rejected at validation (OK)
- test_fail_fast_skips_downstream
  fail_fast: a=failed, b=skipped, error='ValueError: nope' (OK)
- test_parallel_faster_than_sequential
  parallel 3x200ms ran in 201ms (OK)
- test_rate_limit_throttles
  6 tasks @ 5/s throttled to 202ms (OK)
- test_retry_then_succeed
  flaky task succeeded on attempt 3, retries=2 (OK)

all 7 tests passed
```

---

## 5. Python reference SDK — runnable example

Runs the market-analysis workflow fully offline (MockLLM, no API key needed):

```bash
cd /Users/manikandankasi/Desktop/mani/dev/orchestrator/sdk-python

python3 examples/run_market.py
```

You should see a full JSON report followed by:
```
--- summary ---
status        : succeeded
duration_ms   : ~55
critical_path : fetch_prices
output        : {'ticker': 'AAPL', 'last': 199.4, 'sentiment': 'net-negative', 'recommendation': 'HOLD'}
```

---

## 6. End-to-end: Python client ↔ Go engine (the real contract)

This test spawns the Go binary as a child process, exchanges NDJSON messages,
and verifies 7 scenarios against the live engine.

```bash
cd /Users/manikandankasi/Desktop/mani/dev/orchestrator/engine

python3 ../sdk-python/tests/test_go_engine.py ./orchestrator
```

Expected output:
```
Go engine binary: .../engine/orchestrator
Running 7 end-to-end tests

- basic run (market-analysis, 4 tasks)
  status=succeeded, duration=0ms, output={...HOLD...}, critical_path=fetch_prices → report
- parallelism (a∥b then join c)
  a��b+c: 205ms (threshold 360ms) ✓
- fail-fast: failed task → downstream skipped
  boom=failed, after=skipped ✓
- retry (retryable error, succeeds attempt 3)
  succeeded on attempt 3, retries=2 ✓
- continue-on-error isolates branch
  bad=failed, dep=skipped, ind=succeeded ✓
- decisions surfaced in task spans
  decisions=['chose strategy A', 'adjusted threshold'] ✓
- template resolution (input + task output)
  template resolved, output=wrapped:price:300 ✓

7/7 passed
```

What each test proves:

| Test | What it verifies |
|---|---|
| basic run | DAG executes, 4 skills complete, `output` resolved, `critical_path` non-empty |
| parallelism | `fetch_prices` ∥ `fetch_news` — two 200ms tasks finish in ~200ms total, not 400ms |
| fail-fast | Failed task halts the run; downstream tasks are `skipped` in the report |
| retry | Engine re-dispatches skill on retryable error; `attempts=3`, `retries=2` in report |
| continue-on-error | Failed branch is isolated; independent tasks still complete |
| decisions | `ctx.record_decision(...)` values appear in the task span in the report |
| template resolution | `${input.x}` and `${taskId.output}` are resolved by the engine before dispatch |

---

## 7. Run everything at once

```bash
cd /Users/manikandankasi/Desktop/mani/dev/orchestrator/engine

# Go unit tests (race detector on)
go test -race ./...

# Python SDK unit tests
python3 ../sdk-python/tests/test_engine.py

# End-to-end (Go binary ↔ Python client)
python3 ../sdk-python/tests/test_go_engine.py ./orchestrator
```

All three should exit 0 with no failures.

---

## Troubleshooting

**`go test` fails with import errors**
The module path in `go.mod` is `github.com/org/orchestrator`. If you move the `engine/` directory,
update `go.mod` accordingly: `go mod edit -module <new/path>`.

**Binary not found in end-to-end test**
Build it first: `go build -o orchestrator ./cmd/orchestrator`

**PyYAML not installed — YAML spec fails to load**
The YAML spec is optional. All tests use the JSON spec (`spec/examples/market-analysis.json`).
Install with `pip install pyyaml` if you want YAML support.

**Rate-limit test is flaky on a slow machine**
The rate-limit test asserts `elapsed >= 150ms` for a 5-req/s bucket with 6 tasks.
On very slow machines increase the threshold; the bucket logic itself is correct.
