# orchestrator (Python reference SDK)

In-process workflow orchestration engine + authoring API. Zero required dependencies
(stdlib `asyncio`); `pyyaml` is optional (for `.yaml` specs), `anthropic` optional (for the
real LLM adapter).

## Concepts

- **Workflow** — a DAG of tasks loaded from a template (`Workflow.from_file/from_dict/from_json`).
- **Skill** — a registered handler `(ctx, inputs) -> output`, sync or `async`.
- **Tool** — a registered callable a skill invokes via `ctx.call_tool(...)`.
- **Orchestrator** — runs a workflow, enforcing concurrency + rate limits, and returns a `Report`.

## Minimal usage

```python
from orchestrator import Workflow, Orchestrator, Registry, MockLLM

reg = Registry()

@reg.tool("http.get")
def http_get(url):
    return {"url": url, "ok": True}

@reg.skill("market.fetch")
def fetch(ctx, inputs):
    ctx.call_tool("http.get", url=f"/prices/{inputs['ticker']}")
    ctx.record_decision("selected primary feed", rationale="lowest latency")
    return {"ticker": inputs["ticker"], "last": 199.4}

@reg.skill("llm.classify")
def classify(ctx, inputs):
    r = ctx.llm(messages=[{"role": "user", "content": inputs["text"]}], model="claude-opus-4-8")
    return r.text

wf = Workflow.from_file("../spec/examples/market-analysis.json")
report = Orchestrator(reg, llm=MockLLM()).run_sync(wf, inputs={"ticker": "AAPL"})
print(report.to_json())
```

## The `ctx` (SkillContext) API

| Member | Purpose |
|---|---|
| `ctx.inputs` | resolved task inputs |
| `ctx.call_tool(name, **kwargs)` | invoke a registered tool |
| `ctx.llm(messages, tools=, model=, **opts)` | call the configured LLM provider; usage is recorded |
| `ctx.record_decision(summary, rationale=, data=)` | append a critical decision to the trace |
| `ctx.log(msg)`, `ctx.attempt`, `ctx.cancelled` | logging / retry attempt / cooperative cancel flag |

## Report

`report.to_dict()` / `report.to_json()` give: `status`, `duration_ms`, per-task
`{status, duration_ms, attempts, llm, decisions, error}`, `critical_path` (bottleneck chain),
`totals` (llm tokens, tool calls, retries), `errors`, and the resolved `output`.

## Run

```bash
python3 examples/run_market.py
python3 tests/test_engine.py
```

## Using a real LLM

```python
from orchestrator import AnthropicProvider, Orchestrator
orch = Orchestrator(reg, llm=AnthropicProvider(model="claude-opus-4-8"))  # needs ANTHROPIC_API_KEY + `pip install anthropic`
```
Confirm current Claude model IDs/limits from the Claude API reference before pinning them.
