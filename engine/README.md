# Orchestrator Engine (Go)

The shared orchestration core. Single static binary. Drives the DAG scheduler,
concurrency pool, rate limiting, retries, and report. All thin-client SDKs
(Python, Java, JS/TS) talk to this binary via the **embedded stdio transport**
or the **gRPC service**.

## Source layout

```
engine/
  cmd/orchestrator/main.go       entry point — embedded mode + server mode flag
  internal/
    spec/
      spec.go                    workflow spec types, JSON parser, DAG validation
      spec_test.go
      template.go                ${...} template resolution
    ratelimit/
      bucket.go                  goroutine-safe token-bucket limiter (NullBucket fallback)
    report/
      report.go                  Report / TaskSpan / Totals types + critical-path algorithm
    scheduler/
      scheduler.go               DAG scheduler: worker pool, rate limiting, retries, fail-fast
      scheduler_test.go
  transport/
    stdio/
      stdio.go                   embedded transport: NDJSON over stdin/stdout
    grpc/
      server.go                  gRPC service (needs `make proto` + `-tags grpc` build)
  go.mod
  Makefile
```

## Embedded (stdio) transport protocol

The binary is spawned as a child process by the thin-client SDKs. Communication
is **newline-delimited JSON (NDJSON)** over stdin/stdout. All messages are one
JSON object per line.

```
Client → Engine (stdin):
  {"type":"start_run","spec_json":"...","inputs_json":"..."}
  {"type":"skill_result","invocation_id":"...","output_json":"...","error":null,"decisions":[...],"llm_usage":null}
  {"type":"cancel_run","run_id":"..."}

Engine → Client (stdout):
  {"type":"run_accepted","run_id":"r_..."}
  {"type":"skill_invocation","invocation_id":"...","run_id":"...","task_id":"...","skill":"...","inputs_json":"...","attempt":1}
  {"type":"event","run_id":"...","task_id":"...","event_type":"task.started","at_unix_ms":...}
  {"type":"report","run_id":"...","status":"succeeded","duration_ms":...,...}  ← final
```

Multiple `skill_invocation` messages can be in-flight at once (one per task running
in parallel). Each `skill_result` is correlated by `invocation_id`.

## Build

```bash
# Install Go 1.21+: https://go.dev/dl/
cd engine
go build -o orchestrator ./cmd/orchestrator        # embedded mode
go test ./...                                       # run unit tests

# Server mode (gRPC — needs protoc):
make proto                                          # generates transport/grpc/gen/
go build -tags grpc -o orchestrator ./cmd/orchestrator
```

## Run (embedded, direct)

```bash
echo '{"type":"start_run","spec_json":"{\"workflow\":{\"name\":\"x\",\"tasks\":[{\"id\":\"a\",\"skill\":\"s\"}]}}","inputs_json":"{}"}' \
  | ./orchestrator
# Engine will send skill_invocation for task "a" and then block waiting for skill_result.
```
