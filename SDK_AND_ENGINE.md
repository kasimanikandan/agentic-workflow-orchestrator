# Agentic Workflow Orchestrator — SDK & Engine Architecture

Complete guide to understanding the relationship between the Python SDK and the Go orchestrator engine.

---

## Overview

The **agentic-workflow-orchestrator** consists of two components:

| Component | Language | Role | Distribution |
|---|---|---|---|
| **Python SDK** | Python 3.9+ | Client library for authoring and running workflows | PyPI package: `agentic-workflow-orchestrator` |
| **Orchestrator Engine** | Go 1.21+ | Shared DAG scheduler, rate limiter, resilience | Standalone binary + embedded in Python SDK |

Both are **included in the complete package**, but they can be used independently.

---

## Architecture

```
User's Python Application
        ↓
    Python SDK
    (agentic-workflow-orchestrator)
        ↓
    ┌──────────────────────────────────┐
    │  TWO EXECUTION MODES             │
    ├──────────────────────────────────┤
    │  Mode 1: In-Process (Python)     │  ← Default, no external deps
    │  - Pure Python scheduler         │
    │  - DAG walk, concurrency         │
    │  - Rate limiting                 │
    │                                  │
    │  Mode 2: External (Go Engine)    │  ← Recommended for prod
    │  - Spawn `orchestrator` binary   │
    │  - stdio / gRPC protocol         │
    │  - Same semantics, different impl│
    └──────────────────────────────────┘
        ↓
    Skills + Tools (user code)
        ↓
    LLM calls (optional, within skills) → Anthropic / OpenAI / Gemini / xAI / HF / Azure
    MCP calls (optional, within skills) → MCP servers
```

---

## Execution Modes

### Mode 1: In-Process Python Engine (Default)

**When to use:** Development, testing, single-machine workflows, when you want zero external dependencies.

**How it works:**
```python
from orchestrator import Orchestrator, Registry, Workflow

wf = Workflow.from_file("workflow.json")
orch = Orchestrator(registry)
report = orch.run_sync(wf, inputs={})
```

**Characteristics:**
- ✅ Zero external dependencies
- ✅ Pure Python (no subprocess overhead)
- ✅ Full GIL contention on multi-core (Python limitation)
- ✅ Immediate execution feedback
- ❌ Not optimized for high-throughput parallelism

**Engine:** Built-in Python scheduler in `orchestrator.engine` module.

---

### Mode 2: External Go Engine (Recommended)

**When to use:** Production, high-concurrency workflows, CPU-intensive tasks, when you want true parallelism.

**How it works:**
```python
from orchestrator import Orchestrator, Registry, Workflow

wf = Workflow.from_file("workflow.json")
orch = Orchestrator(registry, engine="go", engine_path="/path/to/orchestrator")
report = orch.run_sync(wf, inputs={})
```

**Characteristics:**
- ✅ True parallelism (no GIL)
- ✅ Highly optimized DAG scheduler
- ✅ Battle-tested concurrency primitives
- ✅ Better latency for high-concurrency workflows
- ✅ Can use gRPC for multi-process setups
- ❌ Requires Go binary (included in package)
- ❌ Subprocess overhead (~50ms startup)

**Engine:** Go binary (`orchestrator`) communicates via NDJSON over stdio.

---

## Python SDK Package Contents

### What's in `pip install agentic-workflow-orchestrator`

```
agentic-workflow-orchestrator/
├── orchestrator/                (Python SDK)
│   ├── engine.py               (in-process scheduler)
│   ├── registry.py             (skill registration)
│   ├── llm.py                  (LLM provider adapters)
│   ├── spec.py                 (workflow parsing)
│   ├── report.py               (execution reports)
│   ├── ratelimit.py            (token bucket)
│   └── mcp_integration.py       (MCP support)
│
└── orchestrator/bin/           (included binaries)
    └── orchestrator            (Go engine binary, platform-specific)
```

The **Go engine binary is bundled** with the Python package. Users don't need to install Go separately.

---

## Dependencies

### Core SDK: Zero External Dependencies

```python
# Pure Python — works offline, no pip installs needed beyond Python itself
from orchestrator import Orchestrator, Registry, Workflow
```

### Optional: LLM Support

```bash
# Add Anthropic Claude support
pip install agentic-workflow-orchestrator[llm]
```

Installs: `anthropic>=0.7.0`

### Optional: Development

```bash
# Add testing + code quality tools
pip install agentic-workflow-orchestrator[dev]
```

Installs: `pytest`, `pytest-cov`, `black`, `isort`, `mypy`

### Optional: Engine (already included)

```bash
# Explicitly listed as optional dependency (but pre-packaged)
pip install agentic-workflow-orchestrator[engine]
```

The Go binary is **already included** in all installations; this is just a documentation marker.

---

## How the Go Engine is Packaged

### Build Process

1. Go engine source: `engine/cmd/orchestrator/main.go`
2. Compiled for multiple platforms during build:
   - `orchestrator-darwin-arm64` (macOS M1/M2)
   - `orchestrator-darwin-amd64` (Intel macOS)
   - `orchestrator-linux-amd64` (Linux)
   - `orchestrator-windows-amd64.exe` (Windows)
3. Appropriate binary packaged with wheel distribution

### At Install Time

```bash
$ pip install agentic-workflow-orchestrator

# Python SDK installed
# + Included Go binary for your platform
$ python -c "from orchestrator import get_engine_path; print(get_engine_path())"
# /path/to/site-packages/orchestrator/bin/orchestrator-linux-amd64
```

### Using the Go Engine

```python
from orchestrator import Orchestrator, Registry, Workflow, get_engine_path

wf = Workflow.from_file("workflow.json")

# Automatically detect and use included Go binary
orch = Orchestrator(registry, engine="go")
report = orch.run_sync(wf, inputs={})

# Or specify explicitly
orch = Orchestrator(registry, engine="go", engine_path=get_engine_path())
```

---

## Comparison Table

| Feature | Python Engine (in-process) | Go Engine (subprocess) |
|---|---|---|
| **Install overhead** | 0 (already loaded) | ~50ms (subprocess spawn) |
| **Parallelism** | Limited (GIL) | True (OS threads) |
| **Concurrency** | Good for I/O | Excellent for CPU-bound |
| **Max concurrent tasks** | ~100 (Python limitation) | 1000+ |
| **Startup time** | Instant | ~50ms |
| **Memory per task** | ~100KB | ~1KB |
| **Dependencies** | None | None (binary included) |
| **Development** | ✅ Best | ❌ Harder to debug |
| **Production** | ❌ Not recommended | ✅ Recommended |
| **Testing** | ✅ Best | ❌ Slower |

---

## Installation Guide

### Basic Install (Development/Testing)

```bash
# Uses Python in-process engine by default
pip install agentic-workflow-orchestrator
```

Works immediately, no compilation needed.

### Production Install (with LLM support)

```bash
# Includes Anthropic Claude support + Go engine
pip install agentic-workflow-orchestrator[llm]
```

Now you can use both the Python engine (development) and Go engine (production).

### Full Development Setup

```bash
# Clone repo
git clone https://github.com/org/orchestrator
cd orchestrator/sdk-python

# Install with all extras
pip install -e .[llm,dev]

# Verify both engines work
python -c "
from orchestrator import Orchestrator, Registry, Workflow, get_engine_path
print('✓ Python SDK installed')
print(f'✓ Go engine available at: {get_engine_path()}')
"
```

---

## Which Engine Should I Use?

### Use Python Engine If:
- 🔧 You're developing/testing locally
- 📊 You have <100 concurrent tasks
- 🚀 You want instant startup
- 📚 You want to debug easily
- 🧪 You're writing tests

### Use Go Engine If:
- 🏭 Running in production
- 📈 You need 100+ concurrent tasks
- ⚡ You have CPU-intensive skills
- 🔒 You want guaranteed parallelism
- 💾 You need to optimize memory

---

## SDK Version Numbers

**Current:** `0.1.0`

- **SDK version** and **Engine version** are always in sync.
- `agentic-workflow-orchestrator==0.1.0` includes engine v0.1.0.
- Upgrading the SDK upgrades both.

```bash
pip install agentic-workflow-orchestrator==0.2.0  # SDK + Engine both 0.2.0
```

---

## FAQ

**Q: Do I need Go installed to use this SDK?**

A: No. The Go engine binary is pre-compiled and included with the package.

**Q: Can I use just the Python engine for production?**

A: Not recommended. It's suitable for small workflows (<100 tasks). Use the Go engine for production.

**Q: What if I want to use my own Go engine binary?**

A: Pass `engine_path` explicitly:
```python
orch = Orchestrator(registry, engine="go", engine_path="/custom/path/to/orchestrator")
```

**Q: Can I run the Go engine as a separate service?**

A: Yes (v1.1 feature). Currently it only runs embedded (spawned as subprocess). Service mode with gRPC is planned.

**Q: What's the performance difference?**

A: Python engine: ~10-50 tasks/sec. Go engine: ~1000+ tasks/sec (depending on skill duration).

**Q: Do I pay for the Go engine usage?**

A: No, it's open-source and included. Only optional dependencies (Anthropic LLM) incur costs.

---

## Troubleshooting

### "Could not find orchestrator binary"

The Go binary isn't available at its expected location. Try:

```bash
from orchestrator import get_engine_path
import os

path = get_engine_path()
if not os.path.exists(path):
    print(f"Missing: {path}")
    print("Reinstall: pip install --force-reinstall agentic-workflow-orchestrator")
```

### "Python GIL is bottlenecking my workflow"

Switch to the Go engine:

```python
orch = Orchestrator(registry, engine="go")  # instead of default in-process
```

### "I want to debug the engine"

Use the Python engine (it's pure Python and you can step through):

```python
orch = Orchestrator(registry, engine="python")  # or just omit engine= for default
```

---

## Next Steps

1. **Install:** `pip install agentic-workflow-orchestrator`
2. **Quick start:** See [QUICKSTART.md](../QUICKSTART.md)
3. **Examples:** See `sdk-python/examples/`
4. **Docs:** See [DESIGN.md](../DESIGN.md) for architecture

---

**Ready to orchestrate? Get started now!** 🚀
