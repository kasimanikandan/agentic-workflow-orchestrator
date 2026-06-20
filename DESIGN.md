# Multi-Agent Workflow Orchestration SDK — Design

**Status:** Draft v1
**Date:** 2026-06-18
**Architecture decision:** Shared orchestration engine + thin native clients (Python, Java, JS/TS)

---

## 1. Purpose & Goals

A polyglot SDK that takes a **declarative workflow template** describing a use case made of
many tasks — some parallel, some sequential — and **autonomously orchestrates agents and tools**
to complete it, then returns a **complete summary report** (per-agent timing, critical decisions,
outputs, failures).

### Functional goals
- Author a workflow once as language-neutral data (YAML/JSON); run it from Python, Java, or JS.
- Auto-derive parallelism vs. ordering from a task dependency graph (DAG) — caller never hand-threads.
- **Concurrency** with a bounded worker pool **and rate limiting** (global + per-provider).
- **Agents** can use **tools** and optionally call an **LLM** when a task needs reasoning.
- Produce a structured **report**: status, per-task duration, retries, LLM token usage, recorded
  "critical decisions", and the **critical path** (the bottleneck chain).
- Resilience: retries, timeouts, cancellation, fail-fast vs. continue.

### Non-goals (v1)
- A visual workflow designer / UI.
- Long-running human-in-the-loop approvals (designed for, but not implemented in v1).
- Cross-datacenter distributed execution (single-engine process or cluster of equals in v1).

---

## 2. Core Concepts

| Concept | Definition |
|---|---|
| **Spec** | Declarative description of *what* a task needs: inputs, outputs, success criteria, which skill handles it. |
| **Skill** | A reusable, named capability (`market.fetch`, `llm.classify`). Backed by code, a tool, or an LLM prompt. The unit agents are built from. |
| **Agent** | The runtime worker assigned to a task. Selects skills/tools, optionally reasons via LLM, produces a result. |
| **Tool** | A concrete callable the agent can invoke (HTTP API, DB query, shell, function). |
| **Workflow** | A DAG of tasks. Edges = dependencies. This is the template you author. |
| **Orchestrator** | The engine: walks the DAG, schedules ready tasks, enforces concurrency + rate limits, collects results, builds the report. |
| **Run** | One execution of a workflow with concrete inputs; has its own state and trace. |

**Guiding principle:** the workflow template is *language-neutral data*. Each language ships a
thin native SDK that authors/loads the template and registers skills; one shared engine executes it.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Workflow Spec (YAML/JSON)  ← single source of truth     │
└─────────────────────────────────────────────────────────┘
        │ authored & loaded by native SDKs
        ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Python SDK  │  │   Java SDK   │  │   JS/TS SDK  │   thin clients
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       └─────────────────┼─────────────────┘
                         │ gRPC / protobuf (bi-directional streaming)
                         ▼
        ┌───────────────────────────────────┐
        │   Orchestrator Core (the engine)   │   single correct impl
        │  - DAG scheduler                   │
        │  - Concurrency pool + rate limiter │
        │  - Retry / timeout / cancellation  │
        │  - State store (pluggable)         │
        │  - Trace + report collector        │
        └──────┬──────────────┬──────────────┘
               ▼              ▼
      ┌────────────────┐  ┌──────────────────────┐
      │ Skill / Tool   │  │ LLM Provider Adapter  │
      │ Registry       │  │ (Anthropic/OpenAI/...) │
      └────────────────┘  └──────────────────────┘
```

### 3.1 Chosen approach: Shared engine + thin clients
- **One orchestration core** (recommended impl language: **Go** or **Rust** for a single static binary,
  strong concurrency primitives, and easy cross-language distribution). It owns the scheduler,
  concurrency pool, rate limiter, retries, state, and report.
- **Native SDKs** (Python, Java, JS/TS) are thin clients over **gRPC + protobuf**. They:
  1. Author/validate workflow specs.
  2. Register **skill handlers** (callbacks) with the engine.
  3. Start runs and stream back events/reports.

### 3.2 Skill execution model (how callbacks reach client code)
Skills are implemented in the *client* language but executed under engine control. Two transports,
both over the same gRPC channel:

- **Skill-dispatch stream (recommended default):** The client opens a long-lived bidirectional
  stream. When the engine schedules a task, it sends a `SkillInvocation` down the stream; the client
  runs the registered handler in its own process and returns a `SkillResult`. This keeps skill code
  **in-process** in the client (full access to its libraries) while the engine retains scheduling,
  concurrency, and rate-limit control.
- **Tool endpoints (optional):** Stateless tools can be registered as HTTP/gRPC endpoints the engine
  calls directly — useful for language-agnostic shared tools.

> Rationale: this gives us *one* correct scheduler + rate limiter (no behavioral drift across
> languages) while letting each language keep idiomatic, in-process skill code.

### 3.3 Deployment modes
- **Embedded:** engine binary shipped with the SDK, spawned as a child process / sidecar; gRPC over a
  local unix socket. Zero-ops for single-machine use.
- **Service:** engine runs as a shared service; many clients submit workflows. Enables durable,
  resumable, multi-tenant runs.

---

## 4. Workflow Spec (the template)

### 4.1 Example
```yaml
workflow:
  name: market-analysis
  version: 1

  concurrency:
    max_parallel: 8                      # global worker-pool size
    rate_limit: { requests: 60, per: 1m }# global token bucket

  providers:                             # per-provider rate buckets
    anthropic: { rate_limit: { requests: 50, per: 1m, tokens: 100000, per_tokens: 1m } }
    market_api: { rate_limit: { requests: 20, per: 1s } }

  defaults:
    retry:   { max: 3, backoff: exponential, base: 500ms, jitter: true }
    timeout: 120s
    on_error: fail_fast                  # fail_fast | continue

  inputs:
    ticker: { type: string, required: true }

  tasks:
    - id: fetch_prices
      skill: market.fetch
      provider: market_api
      inputs: { ticker: "${input.ticker}" }

    - id: fetch_news
      skill: news.fetch                  # no depends_on -> PARALLEL with fetch_prices
      provider: market_api
      inputs: { ticker: "${input.ticker}" }

    - id: sentiment
      skill: llm.classify                # LLM-backed skill
      provider: anthropic
      depends_on: [fetch_news]
      inputs: { text: "${fetch_news.output}" }

    - id: report
      skill: analysis.summarize
      depends_on: [fetch_prices, sentiment]  # join -> waits for BOTH
      inputs:
        prices:    "${fetch_prices.output}"
        sentiment: "${sentiment.output}"

  output: "${report.output}"
```

### 4.2 Semantics
- **Parallelism is derived:** any task whose `depends_on` set is satisfied becomes *ready* and is
  dispatched. Tasks with no shared dependency run concurrently (subject to `max_parallel` + buckets).
- **Ordering is explicit:** `depends_on` creates edges; a task with multiple deps is a **join**.
- **Templating:** `${input.x}`, `${<task_id>.output}`, and `${<task_id>.output.field}` are resolved
  from prior results at dispatch time.
- **Validation:** spec is checked for a valid DAG (no cycles), resolvable references, and known skills
  before any task runs.

### 4.3 Authoring options
- **Static:** write YAML/JSON and load it.
- **Programmatic:** build the same graph via a native builder API (section 8) — useful when the graph
  is dynamic. Both compile to the identical internal representation.

---

## 5. Execution Engine

### 5.1 Scheduler
- Topological walk of the DAG. Maintains:
  - `ready`  — deps satisfied, awaiting a worker + token.
  - `running` — dispatched to the pool.
  - terminal — `succeeded | failed | skipped`.
- On task completion, downstream tasks are re-evaluated; newly-ready ones enter `ready`.

### 5.2 Concurrency
- A **bounded worker pool** sized by `max_parallel`. A task needs a free worker slot to run.
- Workers are engine-side; actual skill code runs in the client via the dispatch stream, so
  `max_parallel` bounds *in-flight tasks*, not OS threads in the client.

### 5.3 Rate limiting
- **Global token bucket** in front of dispatch (`concurrency.rate_limit`).
- **Per-provider buckets** (`providers.*.rate_limit`) so LLM RPM/TPM caps don't starve non-LLM tasks,
  and vice-versa. LLM buckets support both **request** and **token** limits.
- A task must acquire *both* the global token and its provider token before running; otherwise it
  waits (non-blocking; the slot is yielded to other ready tasks).

### 5.4 Resilience
- **Retry:** per-task policy (`max`, `backoff`, `jitter`). Retries re-acquire rate tokens.
- **Timeout:** per-task wall-clock; on expiry the task is cancelled and treated as a failure.
- **Cancellation:** cancelling a run propagates cooperative cancellation to in-flight skill handlers.
- **Failure policy:** `fail_fast` aborts the run and cancels in-flight siblings; `continue` marks the
  failed task and its unreachable descendants as `skipped` and proceeds with the rest.
- **Idempotency:** skills may declare `idempotent: true` to allow safe retry; non-idempotent skills
  retry only if they failed before any side effect (best-effort, documented caveat).

### 5.5 State store (pluggable)
- `InMemory` (default) — fast, non-durable.
- `Redis` / `SQL` — durable, **resumable** runs (re-attach to a run, replay completed tasks from
  stored outputs). Enables the Service deployment mode and crash recovery.

---

## 6. Agents, Skills & Tools

### 6.1 Skill kinds
- **Code skill:** a registered function `(ctx, inputs) -> output`. Pure orchestration logic / IO.
- **Tool skill:** thin wrapper that calls one registered tool.
- **LLM skill:** prompt template + optional tool schema + output parser; may run a tool-use loop.

### 6.2 Skill context (`ctx`)
Passed to every handler; the bridge back to the engine:
- `ctx.inputs` — resolved inputs.
- `ctx.callTool(name, args)` — invoke a registered tool (engine meters it against its provider bucket).
- `ctx.llm(...)` — call the configured LLM provider (see §7).
- `ctx.recordDecision(summary, rationale?, data?)` — append a **critical decision** to the trace.
- `ctx.log(...)`, `ctx.cancelled` (cooperative cancel flag), `ctx.attempt` (retry counter).

### 6.3 Agent loop (for LLM skills)
```
1. Render prompt from template + inputs.
2. Call LLM with optional tool schema.
3. If model requests a tool -> engine runs the registered tool (rate-limited) -> feed result back.
4. Repeat until model returns a final answer or max-steps reached.
5. Parse/validate output against the task's output spec.
Each tool choice + final rationale is auto-captured as a decision.
```

---

## 7. LLM Integration

**CRITICAL:** LLM is **NOT** used for orchestration (scheduling, DAG walk, rate limiting). LLM is used
**WITHIN skills** for reasoning. The orchestrator itself is always deterministic.

LLM is *just another skill backend*, behind a provider interface so it is optional and swappable.

```
interface LlmProvider {
  complete(messages, tools?, opts) -> { text, toolCalls, usage{in,out}, stopReason }
}
```

### Supported Providers

| Provider | Models | Status | Install |
|---|---|---|---|
| **MockLLM** | Deterministic (testing) | ✅ | Built-in (zero-dep) |
| **Anthropic** | Claude 3.x (Opus, Sonnet, Haiku) | ✅ | `[llm-anthropic]` |
| **OpenAI** | GPT-4, GPT-3.5-turbo | ✅ | `[llm-openai]` |
| **Google Gemini** | Gemini 1.5 Pro, Pro Vision | ✅ | `[llm-gemini]` |
| **xAI** | Grok Beta | ✅ | `[llm-xai]` |
| **Hugging Face** | Llama, Mistral, Phi (local/API) | ✅ | `[llm-huggingface]` |
| **Azure OpenAI** | Enterprise GPT-4 | ✅ | `[llm-azure]` |

### Default Recommendation

- **Anthropic Claude** is the default (best reasoning + tool use).
- **Models:** Opus 4.8 for hard reasoning, Sonnet 4.6 for cost/latency balance, Haiku 4.5 for simple tasks.
- **Overridable per skill:** skills can request a different provider/model.

### Execution Model

- **Tool use:** the engine maps the model's tool-call requests to registered tools and loops (§6.3).
- **Rate limiting:** every LLM call passes through that provider's **request + token** bucket.
- **Token tracking:** tokens in/out are recorded per task in the report (for cost attribution).
- **No orchestration use:** skills can optionally call `ctx.llm(...)`, but the scheduler **never** calls LLM.

### Skills vs. Orchestration

```
Orchestration (always deterministic):
  DAG walk → task scheduling → concurrency → rate limits → retries → reporting

Skills (optional LLM):
  Task handler calls ctx.llm(messages, model) if needed for reasoning/classification/generation
  Results tracked in report for cost attribution
```

See `LLM_INTEGRATION.md` for complete provider guide and usage patterns.

---

## 8. Native Client APIs (same spec, idiomatic feel)

### Python
```python
from orchestrator import Workflow, Orchestrator, skill

wf = Workflow.from_yaml("market.yaml")

@skill("market.fetch")
async def fetch(ctx, ticker: str):
    data = await ctx.call_tool("http.get", url=f"/prices/{ticker}")
    ctx.record_decision("selected primary feed", rationale="lowest latency")
    return data

orch = Orchestrator(engine="embedded")          # spawns local engine binary
result = await orch.run(wf, inputs={"ticker": "AAPL"})
print(result.report.as_json())
```

### JavaScript / TypeScript
```ts
import { Workflow, Orchestrator, registerSkill } from "@org/orchestrator";

const wf = Workflow.fromYaml("market.yaml");

registerSkill("market.fetch", async (ctx, { ticker }) => {
  const data = await ctx.callTool("http.get", { url: `/prices/${ticker}` });
  ctx.recordDecision("selected primary feed", { rationale: "lowest latency" });
  return data;
});

const orch = new Orchestrator({ engine: "embedded" });
const result = await orch.run(wf, { ticker: "AAPL" });
console.log(result.report.toJSON());
```

### Java
```java
Workflow wf = Workflow.fromYaml("market.yaml");

registry.skill("market.fetch", (ctx, in) -> {
    var data = ctx.callTool("http.get", Map.of("url", "/prices/" + in.get("ticker")));
    ctx.recordDecision("selected primary feed", "lowest latency");
    return data;
});

Orchestrator orch = Orchestrator.embedded();
Result r = orch.run(wf, Map.of("ticker", "AAPL"));
System.out.println(r.report().toJson());
```

All three load the **same template**, register skills, and get the **same engine semantics**.

---

## 9. The Summary Report

Every task runs inside a **trace span**; the engine assembles a structured report at completion.

```json
{
  "workflow": "market-analysis",
  "run_id": "r_01J...",
  "status": "succeeded",
  "started_at": "2026-06-18T16:00:00Z",
  "duration_ms": 4120,
  "tasks": [
    { "id": "fetch_prices", "status": "succeeded", "duration_ms": 210, "attempts": 1 },
    { "id": "fetch_news",   "status": "succeeded", "duration_ms": 360, "attempts": 1 },
    {
      "id": "sentiment", "status": "succeeded", "duration_ms": 1830, "attempts": 1,
      "llm": { "provider": "anthropic", "model": "claude-...", "tokens_in": 1200, "tokens_out": 340 },
      "decisions": [
        { "at_ms": 900, "summary": "classified news as net-negative (conf 0.81)",
          "rationale": "3 of 5 headlines cite guidance cut" }
      ]
    },
    { "id": "report", "status": "succeeded", "duration_ms": 720, "attempts": 1 }
  ],
  "critical_path": ["fetch_news", "sentiment", "report"],
  "totals": { "llm_tokens_in": 1200, "llm_tokens_out": 340, "tool_calls": 4, "retries": 0 },
  "errors": []
}
```

- **Critical decisions:** from `ctx.recordDecision(...)` for code skills, and auto-captured tool
  choices + final rationale for LLM skills.
- **Critical path:** the longest dependency chain by duration — shows where wall-clock actually went.
- **Streaming:** clients may subscribe to a live event stream (`task.started`, `task.succeeded`,
  `decision.recorded`, ...) in addition to the final report.

---

## 10. Cross-Language Contract

- **`spec.schema.json`** — JSON Schema for the workflow template. The one source of truth; all SDKs
  validate against it.
- **`orchestrator.proto`** — gRPC service: `RunWorkflow`, `SkillDispatch` (bidi stream),
  `StreamEvents`, `GetReport`, `CancelRun`.
- **Conformance suite** — language-neutral fixtures (spec + inputs + expected report shape) that every
  SDK + engine build must pass. Guards against drift even though the engine is shared.

---

## 11. Repository Layout (proposed)

```
orchestrator/
  DESIGN.md                 # this document
  spec/
    spec.schema.json        # workflow template schema
    examples/               # sample workflows
  proto/
    orchestrator.proto      # gRPC contract
  engine/                   # the shared core (Go/Rust)
    scheduler/  ratelimit/  state/  report/  llm/
  sdk-python/
  sdk-js/
  sdk-java/
  conformance/              # shared fixtures + expected outputs
```

---

## 12. Phased Plan

1. **Spec & contract** — finalize `spec.schema.json` + `orchestrator.proto`; lock semantics.
2. **Engine MVP** — DAG scheduler, worker pool, global + per-provider rate limiter, in-memory state,
   report builder, skill-dispatch stream.
3. **Reference SDK (Python)** — authoring, skill registration, `ctx`, run + report; embedded engine.
4. **LLM adapter** — Anthropic (Claude) first, with tool-use loop + token-aware rate limiting.
5. **Resilience** — retries, timeouts, cancellation, fail-fast/continue, durable state (Redis/SQL).
6. **JS + Java SDKs** — built against the conformance suite.
7. **Service mode** — multi-tenant engine, resumable runs, live event streaming.

---

## 12.5 MCP Integration (v1 feature)

The Orchestrator supports flexible MCP (Model Context Protocol) server integration at three levels:

### Level 1 — Direct tool calls (stateless)
```python
@reg.tool("mcp.filesystem.read")
def mcp_fs_read(path: str):
    # Spawn server on demand, call tool, return result
    # No caching, no lifecycle management
    pass

@reg.skill("analyze")
def analyze(ctx, inputs):
    ctx.call_tool("mcp.filesystem.read", path=inputs["file"])
```
**Use case:** One-off tool calls, don't need semantic wrapping.

### Level 2 — Pre-wrapped MCP skills (semantic, reusable)
```python
from orchestrator.mcp_integration import mcp_skill

@mcp_skill("filesystem", "read_file")
def fs_read(ctx, inputs):
    # MCP server spawned automatically
    # Tool result available as ctx._mcp_result
    # Feels like a normal skill to the caller
    pass
```
**Use case:** Frequently used operation, want clean semantic interface. Hide MCP details.

### Level 3 — Managed MCP servers (cached, lifecycle-managed)
```python
mcp_registry = ManagedMCPRegistry()
mcp_registry.register("filesystem", tools=["read", "list"])

@reg.skill("complex_analysis")
def analyze(ctx, inputs):
    # Get or spawn server (cached for subsequent tasks)
    server = mcp_registry.get_or_spawn("filesystem")
    
    # Multiple calls to same server reuse connection
    files = server.call_tool("list", {...})
    content = server.call_tool("read", {...})
    
    # Cleanup: mcp_registry.cleanup() at end of run
```
**Use case:** Multiple MCP calls, need connection pooling + lifecycle management. Perfect for complex multi-call analysis.

### Design notes
- All three levels coexist in the same workflow (mix and match)
- Level 3 servers are cached across tasks — reused automatically
- Orchestrator meters MCP tool calls against a per-provider rate bucket
- Tool usage and token consumption flow into the report
- Cleanup is automatic when the run completes (try/finally pattern)

Example: [examples/04_mcp_flexible_workflow.py](sdk-python/examples/04_mcp_flexible_workflow.py)

---

## 13. Decisions (resolved)

| Question | Decision | Rationale |
|---|---|---|
| Engine implementation language | **Go** | Single static binary, first-class concurrency, fastest to ship; Rust's extra safety not worth the velocity cost here. |
| Durable state backend (first) | **Redis** | Simplest path to resumable runs + live event streaming. SQL/Postgres added later for rich report querying. |
| Dynamic fan-out / sub-workflows | **Defer to v1.1** (`foreach` map-fan-out) | Static DAG already covers "some parallel / some sequential". Add runtime fan-out next. |
| Human-in-the-loop pause/resume | **Deferred** to Service-mode phase | Not needed for the initial autonomous use case. |
| Multi-tenancy & auth | **Deferred** to Service-mode phase | Embedded mode needs no auth; design leaves room for it. |

### Reference implementation note
A **Python reference implementation** (`sdk-python/`) is built first. It runs workflows **in-process**
(no Go engine required) and serves two purposes: (1) a usable SDK today, and (2) the **semantics
oracle** for the conformance suite — the Go engine and the JS/Java SDKs must reproduce its report
shape and scheduling behavior on the shared fixtures.
