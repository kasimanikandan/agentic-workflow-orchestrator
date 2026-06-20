# Quickstart Guide

Get up and running with the Orchestrator SDK in three steps.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.9+ | No pip packages required for these examples |
| Go | 1.21+ | Only needed to compile the engine binary |

---

## Setup

### 1. Build the Go engine

```bash
cd /Users/manikandankasi/Desktop/mani/dev/orchestrator/engine
go build -o orchestrator ./cmd/orchestrator
```

You will see a ~3.6MB `orchestrator` binary. This is the shared engine all
language SDKs talk to. For the Python examples below the SDK runs in-process,
so you do not need to start it manually.

### 2. Set your working directory for examples

```bash
cd /Users/manikandankasi/Desktop/mani/dev/orchestrator/sdk-python
```

All example commands below assume this as the working directory.

---

## Core concepts in 30 seconds

```
Workflow (YAML/JSON)         — what tasks to run and in what order
  └─ Task                    — one unit of work, may depend on others
       └─ Skill              — the handler function that does the work
            └─ Tool          — an external call the skill can make (HTTP, DB, etc.)
            └─ LLM           — an AI model call the skill can make

Orchestrator.run(workflow)   — executes the graph, returns a Report
Report                       — per-task timing, decisions, LLM usage, output
```

Parallelism is derived automatically: tasks with no shared dependency run at the
same time. `depends_on` creates ordering. You never hand-thread anything.

---

## Workflow 1 — Hello World

**Two sequential tasks.** The output of `greet` flows into `shout` via a template
reference. Introduces skill registration and `depends_on`.

### Workflow diagram

```
[greet]  →  [shout]
```

### Run it

```bash
python3 examples/01_hello_world.py
```

### Expected output

```
=== Report ===
  greet       status=succeeded  duration=1ms
               decision: 'composed greeting'  (standard format)
  shout       status=succeeded  duration=0ms

Output : HELLO, WORLD!
Status : succeeded  (1ms total)
```

### How it works

```python
# 1. Define the workflow — tasks + deps + template expressions
SPEC = {
    "workflow": {
        "name": "hello-world",
        "inputs": {"name": {"type": "string", "required": True}},
        "tasks": [
            {
                "id": "greet",
                "skill": "text.greet",
                "inputs": {"name": "${input.name}"}      # resolved from run inputs
            },
            {
                "id": "shout",
                "skill": "text.shout",
                "depends_on": ["greet"],                 # runs AFTER greet
                "inputs": {"text": "${greet.output}"}    # resolved from greet's return value
            }
        ],
        "output": "${shout.output}"
    }
}

# 2. Register skill handlers
reg = Registry()

@reg.skill("text.greet")
def greet(ctx, inputs):
    ctx.record_decision("composed greeting", rationale="standard format")
    return f"Hello, {inputs['name']}!"

@reg.skill("text.shout")
def shout(ctx, inputs):
    return inputs["text"].upper()

# 3. Run
wf     = Workflow.from_dict(SPEC)
report = Orchestrator(reg).run_sync(wf, inputs={"name": "World"})
print(report.output)   # HELLO, WORLD!
```

### Key concepts shown

| Feature | Where |
|---|---|
| `depends_on` | `shout` depends on `greet` — sequential ordering |
| Template `${input.x}` | `greet` receives the run input |
| Template `${taskId.output}` | `shout` receives greet's return value |
| `ctx.record_decision()` | Decision appears in the report under greet's span |

---

## Workflow 2 — Parallel Data Pipeline

**Two independent fetches run at the same time, then merge.** Demonstrates
auto-parallelism, tools, and the join pattern.

### Workflow diagram

```
[fetch_tech] ─┐
               ├─► [merge]
[fetch_finance]┘
```

Both fetch tasks have no `depends_on`, so the engine dispatches them
**concurrently**. `merge` is only dispatched once both complete (a join).

### Run it

```bash
python3 examples/02_parallel_pipeline.py
```

### Expected output

```
=== Report ===
  fetch_tech       status=succeeded  duration=151ms
                   decision: fetched 2 articles from techcrunch
  fetch_finance    status=succeeded  duration=150ms
                   decision: fetched 2 articles from bloomberg
  merge            status=succeeded  duration=0ms
                   decision: merged 2 + 2 = 4 articles

Output  : topic=AI, total=4 articles, sources=['techcrunch', 'bloomberg']
Status  : succeeded  (wall=152ms — fetch_tech∥fetch_finance ran in parallel)
Critical path: fetch_tech

✓ Parallelism confirmed: two 150ms fetches completed in one pass
```

Total wall time is ~150ms, not ~300ms — both fetches ran simultaneously.

### How it works

```python
SPEC = {
    "workflow": {
        "name": "news-aggregator",
        "concurrency": {"max_parallel": 4},           # up to 4 tasks at once
        "tasks": [
            # No depends_on on either fetch → they run in PARALLEL
            {"id": "fetch_tech",    "skill": "feed.fetch", "inputs": {...}},
            {"id": "fetch_finance", "skill": "feed.fetch", "inputs": {...}},
            # depends_on BOTH → waits for both, then runs once (a join)
            {
                "id": "merge",
                "skill": "feed.merge",
                "depends_on": ["fetch_tech", "fetch_finance"],
                "inputs": {
                    "tech":    "${fetch_tech.output}",
                    "finance": "${fetch_finance.output}"
                }
            }
        ]
    }
}

# Tools are registered once; any skill can call them
@reg.tool("http.get")
def http_get(url):
    time.sleep(0.15)           # simulate network latency
    return {"status": 200}

@reg.skill("feed.fetch")
def feed_fetch(ctx, inputs):
    resp = ctx.call_tool("http.get", url=f"https://{inputs['source']}.com/api")
    ctx.record_decision(f"fetched from {inputs['source']}")
    return {"articles": [...], "count": 2}
```

### Key concepts shown

| Feature | Where |
|---|---|
| Parallel tasks | `fetch_tech` and `fetch_finance` — no shared dep |
| Join pattern | `merge.depends_on = ["fetch_tech", "fetch_finance"]` |
| Tools | `ctx.call_tool("http.get", ...)` |
| `concurrency.max_parallel` | Controls worker pool size |
| Retry policy | Per-task `retry: {max: 2, backoff: exponential}` |

---

## Workflow 3 — LLM Content Review Pipeline

**Three sequential tasks using an LLM** to classify content, then routing the
result (approve / flag / reject). Demonstrates LLM skills, per-provider rate
limiting, and multi-step decision recording.

### Workflow diagram

```
[fetch_content] → [moderate (LLM)] → [route]
```

### Run it (offline with MockLLM)

```bash
python3 examples/03_llm_content_review.py
```

### Run it (real Claude — needs API key)

```bash
ANTHROPIC_API_KEY=sk-... python3 examples/03_llm_content_review.py --real
```

### Expected output (MockLLM)

```
=== Content Review Pipeline ===

--- post-001 ---
  content_id : post-001
  action     : approved
  verdict    : label=safe, score=0.1
  [fetch_content] fetched content 'post-001'
  [moderate] moderation verdict: safe (score=0.1)
  [route] routed 'post-001' → approved
  llm tokens : in=21 out=12

--- post-002 ---
  content_id : post-002
  action     : flagged_for_review
  verdict    : label=borderline, score=0.6
  ...

--- post-003 ---
  content_id : post-003
  action     : rejected
  verdict    : label=harmful, score=0.9
  ...
```

### How it works

```python
SPEC = {
    "workflow": {
        "name": "content-review",
        "providers": {
            # Separate rate bucket for LLM calls — won't starve other tasks
            "anthropic": {"rate_limit": {"requests": 50, "per": "1m"}}
        },
        "defaults": {
            "retry":    {"max": 2, "backoff": "exponential", "base": "500ms"},
            "timeout":  "30s",
        },
        "tasks": [
            {"id": "fetch_content", "skill": "content.fetch", ...},
            {
                "id": "moderate",
                "skill": "llm.moderate",
                "provider": "anthropic",       # uses the anthropic rate bucket
                "depends_on": ["fetch_content"],
                "inputs": {"text": "${fetch_content.output.text}"}
            },
            {
                "id": "route",
                "skill": "content.route",
                "depends_on": ["moderate"],
                "inputs": {"verdict": "${moderate.output}"}
            }
        ]
    }
}

@reg.skill("llm.moderate")
def llm_moderate(ctx, inputs):
    # ctx.llm() calls the configured provider (MockLLM or real Claude)
    result = ctx.llm(
        messages=[{"role": "user", "content": f"Moderate: {inputs['text']}..."}],
        model="claude-opus-4-8",
    )
    verdict = json.loads(result.text)
    ctx.record_decision(f"verdict: {verdict['label']} score={verdict['score']}")
    return verdict

# Switch between offline and production with one line:
orch = Orchestrator(reg, llm=MockLLM())                       # offline
orch = Orchestrator(reg, llm=AnthropicProvider("claude-opus-4-8"))  # real Claude
```

### Key concepts shown

| Feature | Where |
|---|---|
| LLM skill | `ctx.llm(messages, model=)` in `llm.moderate` |
| LLM provider swap | `MockLLM()` vs `AnthropicProvider(...)` — one line change |
| Per-provider rate limit | `providers.anthropic.rate_limit` — independent bucket |
| Nested template | `${fetch_content.output.text}` — accesses a field inside output |
| Decisions in report | Every LLM call's verdict is recorded with `ctx.record_decision()` |
| Token usage in report | `report.totals.llm_tokens_in / llm_tokens_out` |

---

## What happens when a task fails

The default is `on_error: fail_fast` — the run stops and all downstream tasks
are marked `skipped`. Set `on_error: continue` on a task to isolate its failure:

```python
{
    "id": "optional_enrichment",
    "skill": "enrich.data",
    "on_error": "continue",      # failure here won't kill the whole run
    "retry": {"max": 2, "backoff": "exponential"}
}
```

The report always shows the full picture:
```json
{
  "status": "failed",
  "tasks": [
    {"id": "optional_enrichment", "status": "failed",  "error": "timeout"},
    {"id": "downstream",          "status": "skipped"},
    {"id": "independent",         "status": "succeeded"}
  ]
}
```

---

## Loading a workflow from a file

```python
# JSON (no deps)
wf = Workflow.from_file("spec/examples/market-analysis.json")

# YAML (requires: pip install pyyaml)
wf = Workflow.from_file("spec/examples/market-analysis.yaml")

# Inline dict (as shown above)
wf = Workflow.from_dict(SPEC)
```

---

## Full example files

| File | What it shows |
|---|---|
| [examples/01_hello_world.py](sdk-python/examples/01_hello_world.py) | Sequential tasks, template resolution, decisions |
| [examples/02_parallel_pipeline.py](sdk-python/examples/02_parallel_pipeline.py) | Parallel tasks, join, tools, retry |
| [examples/03_llm_content_review.py](sdk-python/examples/03_llm_content_review.py) | LLM skill, provider rate limits, MockLLM vs Claude |
| [examples/run_market.py](sdk-python/examples/run_market.py) | Full market analysis (the reference example) |

---

---

## Bonus: MCP Integration (flexible usage)

Use MCP servers from your workflow at any abstraction level:

**Level 1** — Direct tool call (simplest)
```python
@reg.tool("mcp.filesystem.read")
def read_mcp(path): ...

@reg.skill("analyze")
def analyze(ctx, inputs):
    ctx.call_tool("mcp.filesystem.read", path=...)
```

**Level 2** — Pre-wrapped skill (semantic)
```python
from orchestrator.mcp_integration import mcp_skill

@mcp_skill("filesystem", "read_file")
def fs_read(ctx, inputs):
    # MCP handled automatically
    return ctx._mcp_result
```

**Level 3** — Managed servers (advanced, cached)
```python
from orchestrator.mcp_integration import ManagedMCPRegistry

mcp_reg = ManagedMCPRegistry()
mcp_reg.register("filesystem", tools=[...])

@reg.skill("complex_analysis")
def analyze(ctx, inputs):
    server = mcp_reg.get_or_spawn("filesystem")
    # Reuses connection from previous tasks
```

All three work in the same workflow. See [examples/04_mcp_flexible_workflow.py](sdk-python/examples/04_mcp_flexible_workflow.py).

---

## Next steps

- **See all test scenarios:** [TESTING.md](TESTING.md)
- **Full architecture:** [DESIGN.md](DESIGN.md)
- **Workflow schema reference:** [spec/spec.schema.json](spec/spec.schema.json)
- **Add a real LLM:** pass `llm=AnthropicProvider(api_key=os.environ["ANTHROPIC_API_KEY"])` to `Orchestrator()`
- **Use MCP servers:** [examples/04_mcp_flexible_workflow.py](sdk-python/examples/04_mcp_flexible_workflow.py)
