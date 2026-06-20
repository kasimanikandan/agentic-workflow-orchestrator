# LLM Integration Guide

Complete guide to using LLM providers in agentic-workflow-orchestrator.

---

## Critical Distinction: Orchestration vs. Skills

### ❌ LLM is NOT used for Orchestration

The orchestrator engine itself is **completely deterministic**. It does not use LLM for:

- Scheduling tasks
- DAG walk decisions
- Determining parallelism
- Rate limiting logic
- Retry decisions
- Workflow state management

The engine is pure algorithmic: read DAG → execute tasks → enforce dependencies.

### ✅ LLM IS used within Skills

Individual task implementations (skills) can **optionally** call an LLM to perform reasoning.

Example: A skill that classifies user-submitted content might use Claude to determine if content is safe.

```python
from orchestrator import Registry, Workflow, Orchestrator, AnthropicProvider

registry = Registry()

@registry.skill("content.classify")
def classify_content(ctx, inputs):
    """Skill that uses LLM for reasoning."""
    
    # Call LLM via context
    result = ctx.llm(
        messages=[{"role": "user", "content": inputs["text"]}],
        model="claude-opus-4-8",
    )
    
    # LLM analyzed the text; now decide based on its response
    decision = "approve" if "safe" in result.text.lower() else "flag_for_review"
    
    # Record that we made a decision (for auditing)
    ctx.record_decision(
        action=decision,
        rationale=f"LLM classified as: {result.text}",
        llm_model=result.model,
        tokens_used=result.tokens_in + result.tokens_out,
    )
    
    return {"decision": decision, "reasoning": result.text}

# Orchestrator runs the workflow
orch = Orchestrator(registry, llm=AnthropicProvider())
report = orch.run_sync(workflow, {})
```

**Key point:** LLM is a tool *within* a skill, not a scheduler.

---

## Architecture: Three Layers

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Orchestration (deterministic, no LLM)             │
│                                                             │
│  - DAG walk (task dependencies)                            │
│  - Worker pool (concurrent execution)                      │
│  - Rate limiting (token buckets)                           │
│  - Retry logic (exponential backoff)                       │
│  → Always produces same result for same input             │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: Skills (user-defined, may use LLM)               │
│                                                             │
│  - Business logic (fetch, process, analyze, etc.)         │
│  - Optional: call LLM via ctx.llm()                        │
│  - Returns structured output                              │
│  → May call different providers per skill                │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: LLM Providers (pluggable APIs)                    │
│                                                             │
│  - Anthropic Claude                                        │
│  - OpenAI GPT-4/3.5                                        │
│  - Google Gemini                                           │
│  - xAI Grok                                                │
│  - Hugging Face / Local models                            │
│  - Azure OpenAI                                            │
└─────────────────────────────────────────────────────────────┘
```

---

## Supported LLM Providers

### 1. MockLLM — Offline Testing (Default)

Deterministic, no API keys required. Perfect for development and CI/CD.

**When:** Always available, zero dependencies
**Use:** Testing, examples, CI/CD

```python
from orchestrator import MockLLM

llm = MockLLM()
# Always returns deterministic sentiment analysis
# No network calls, no API keys
```

---

### 2. Anthropic (Claude)

Recommended for complex reasoning and tool use.

**Models:** claude-opus-4-8, claude-sonnet-4-6, claude-haiku-4-5

**Install:**
```bash
pip install agentic-workflow-orchestrator[llm-anthropic]
# or
pip install agentic-workflow-orchestrator[llm]  # all providers
```

**Usage:**
```python
from orchestrator import AnthropicProvider

llm = AnthropicProvider(
    model="claude-opus-4-8",
    api_key="your-key"  # or via ANTHROPIC_API_KEY env var
)

orch = Orchestrator(registry, llm=llm)
```

**Cost:** Varies by model (Opus is most expensive, Haiku is cheapest)

---

### 3. OpenAI (GPT-4/GPT-3.5)

High performance, wide model availability.

**Models:** gpt-4, gpt-4-turbo, gpt-3.5-turbo

**Install:**
```bash
pip install agentic-workflow-orchestrator[llm-openai]
```

**Usage:**
```python
from orchestrator import OpenAIProvider

llm = OpenAIProvider(
    model="gpt-4",
    api_key="your-key"  # or via OPENAI_API_KEY env var
)

orch = Orchestrator(registry, llm=llm)
```

**Cost:** Moderate (GPT-4 more expensive than GPT-3.5)

---

### 4. Google Gemini

Multimodal, strong reasoning.

**Models:** gemini-1.5-pro, gemini-pro, gemini-pro-vision

**Install:**
```bash
pip install agentic-workflow-orchestrator[llm-gemini]
```

**Usage:**
```python
from orchestrator import GeminiProvider

llm = GeminiProvider(
    model="gemini-1.5-pro",
    api_key="your-key"  # or via GOOGLE_API_KEY env var
)

orch = Orchestrator(registry, llm=llm)
```

**Cost:** Moderate

---

### 5. xAI (Grok)

Latest frontier models, high performance.

**Models:** grok-beta

**Install:**
```bash
pip install agentic-workflow-orchestrator[llm-xai]
```

**Usage:**
```python
from orchestrator import XAIProvider

llm = XAIProvider(
    model="grok-beta",
    api_key="your-key"  # or via XAI_API_KEY env var
)

orch = Orchestrator(registry, llm=llm)
```

**Cost:** Competitive

---

### 6. Hugging Face / Local Models

Run open-source models locally or via HF API.

**Models:** meta-llama/Llama-2-7b-chat-hf, mistral-7b, etc.

**Install:**
```bash
pip install agentic-workflow-orchestrator[llm-huggingface]
```

**Usage (local):**
```python
from orchestrator import HuggingFaceProvider

llm = HuggingFaceProvider(
    model="meta-llama/Llama-2-7b-chat-hf"
)

orch = Orchestrator(registry, llm=llm)
```

**Usage (Hugging Face Inference API):**
```python
llm = HuggingFaceProvider(
    model="meta-llama/Llama-2-7b-chat-hf",
    api_key="hf_..."  # Hugging Face token
)
```

**Cost:** Free locally, nominal via HF API

---

### 7. Azure OpenAI

Enterprise-grade deployment via Azure.

**Install:**
```bash
pip install agentic-workflow-orchestrator[llm-azure]
```

**Usage:**
```python
from orchestrator import AzureOpenAIProvider

llm = AzureOpenAIProvider(
    deployment_name="my-gpt4-deployment",
    api_key="your-azure-key",
    azure_endpoint="https://my-org.openai.azure.com/",
    api_version="2024-02-01"
)

orch = Orchestrator(registry, llm=llm)
```

**Cost:** Managed by Azure subscription

---

## Installation Scenarios

### Scenario 1: Development Only (No LLM)

```bash
pip install agentic-workflow-orchestrator
```

- Uses MockLLM (deterministic, no keys)
- Perfect for prototyping and testing
- Zero external dependencies

### Scenario 2: Single Provider

```bash
# Just Anthropic Claude
pip install agentic-workflow-orchestrator[llm-anthropic]

# Just OpenAI
pip install agentic-workflow-orchestrator[llm-openai]

# Just Gemini
pip install agentic-workflow-orchestrator[llm-gemini]
```

### Scenario 3: All Providers

```bash
pip install agentic-workflow-orchestrator[llm]
```

Installs all 6 providers (Anthropic, OpenAI, Gemini, xAI, HuggingFace, Azure).

### Scenario 4: Full Development Setup

```bash
pip install agentic-workflow-orchestrator[llm,dev]
```

Includes all providers + testing tools (pytest, black, mypy).

---

## Usage Patterns

### Pattern 1: Simple Classification

```python
@registry.skill("classify.sentiment")
def classify_sentiment(ctx, inputs):
    result = ctx.llm(
        messages=[{"role": "user", "content": inputs["text"]}],
        model="claude-haiku-4-5",  # Cheap model for simple tasks
    )
    return {"sentiment": result.text}
```

### Pattern 2: Complex Reasoning with Tool Use

```python
@registry.skill("analyze.market")
def analyze_market(ctx, inputs):
    tools = [
        {
            "name": "fetch_stock_price",
            "description": "Get current stock price",
            "input_schema": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
            },
        }
    ]
    
    result = ctx.llm(
        messages=[
            {"role": "user", "content": f"Analyze {inputs['ticker']}"}
        ],
        tools=tools,
        model="claude-opus-4-8",  # Better reasoning for complex tasks
    )
    
    # Handle tool calls (if any)
    if result.tool_calls:
        for tc in result.tool_calls:
            print(f"LLM wants to call: {tc['name']} with {tc['input']}")
    
    return {"analysis": result.text}
```

### Pattern 3: Conditional Provider Usage

```python
@registry.skill("process.content")
def process(ctx, inputs):
    if inputs["priority"] == "high":
        # Use expensive, high-quality model
        model = "claude-opus-4-8"
    else:
        # Use cheaper, faster model
        model = "claude-haiku-4-5"
    
    result = ctx.llm(
        messages=[{"role": "user", "content": inputs["text"]}],
        model=model,
    )
    
    return {"result": result.text}
```

### Pattern 4: Multi-Provider Workflow

Different skills can use different LLM providers:

```python
from orchestrator import OpenAIProvider, AnthropicProvider

# Main orchestrator uses Claude by default
orch = Orchestrator(registry, llm=AnthropicProvider())

# But individual skills can override:
@registry.skill("translate")
def translate(ctx, inputs):
    # Override to use OpenAI (better for translation)
    openai = OpenAIProvider()
    result = openai.complete(
        messages=[{"role": "user", "content": f"Translate: {inputs['text']}"}],
    )
    return {"translated": result.text}

# This skill uses the default (Claude)
@registry.skill("analyze")
def analyze(ctx, inputs):
    result = ctx.llm(
        messages=[{"role": "user", "content": inputs["data"]}],
    )
    return {"analysis": result.text}
```

---

## Token Usage Tracking

All LLM calls are automatically tracked in the execution report:

```python
report = orch.run_sync(workflow, {})

for task in report.tasks:
    if task.llm_usage:
        print(f"{task.name}: {task.llm_usage.tokens_in} in, {task.llm_usage.tokens_out} out")
        print(f"  Model: {task.llm_usage.model}")
        print(f"  Provider: {task.llm_usage.provider}")

print(f"Total tokens: {report.totals.llm_tokens_in + report.totals.llm_tokens_out}")
```

---

## Environment Variables

All providers support environment variables for API keys:

| Provider | Environment Variable |
|---|---|
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Google Gemini | `GOOGLE_API_KEY` |
| xAI | `XAI_API_KEY` (not yet standard) |
| Hugging Face | `HUGGINGFACEHUB_API_TOKEN` |
| Azure OpenAI | `AZURE_OPENAI_KEY` + `AZURE_OPENAI_ENDPOINT` |

---

## Error Handling

If an LLM provider is not installed:

```python
from orchestrator import OpenAIProvider

try:
    llm = OpenAIProvider()
    llm.complete(...)
except RuntimeError as e:
    # "pip install 'openai>=1.0.0' to use OpenAIProvider"
    print(e)
```

Skills can catch LLM errors:

```python
@registry.skill("safe.classify")
def classify(ctx, inputs):
    try:
        result = ctx.llm(messages=[...])
        return {"classification": result.text}
    except Exception as e:
        # Fallback: use MockLLM or default logic
        print(f"LLM failed, using fallback: {e}")
        return {"classification": "unknown"}
```

---

## Performance & Cost Optimization

### Use Cheaper Models for Simple Tasks

```python
# Classification? Use haiku
result = ctx.llm(messages=[...], model="claude-haiku-4-5")

# Complex reasoning? Use opus
result = ctx.llm(messages=[...], model="claude-opus-4-8")
```

### Batch LLM Calls in Worker Task

Instead of calling LLM inside a loop, collect requests and batch:

```python
@registry.skill("batch.classify")
def batch_classify(ctx, inputs):
    items = inputs["items"]
    
    # Call once with all items
    result = ctx.llm(
        messages=[{
            "role": "user",
            "content": f"Classify these items: {items}"
        }],
        model="claude-haiku-4-5",
    )
    
    return {"results": result.text}
```

### Cache LLM Responses

Store LLM results if you repeat calls:

```python
cache = {}

@registry.skill("cached.analyze")
def analyze(ctx, inputs):
    text = inputs["text"]
    
    if text not in cache:
        result = ctx.llm(messages=[{"role": "user", "content": text}])
        cache[text] = result.text
    
    return {"analysis": cache[text]}
```

---

## Troubleshooting

### "LLM is None" Error

Ensure you pass an `llm` provider to Orchestrator:

```python
# Wrong
orch = Orchestrator(registry)  # No LLM specified

# Correct
orch = Orchestrator(registry, llm=AnthropicProvider())
```

### API Key Not Recognized

Verify environment variable or constructor argument:

```bash
export ANTHROPIC_API_KEY="sk-..."
python my_workflow.py
```

Or pass explicitly:

```python
llm = AnthropicProvider(api_key="sk-...")
```

### Rate Limiting / Quota Exceeded

The orchestrator has built-in rate limiting via token buckets. Additionally, some providers have rate limits:

```python
from orchestrator import TokenBucket

# 60 tokens per minute
bucket = TokenBucket(capacity=60, refill_rate=1)

# Check before calling
if bucket.consume(10):
    result = ctx.llm(messages=[...])
else:
    print("Rate limited, retrying...")
```

---

## Summary

| Feature | Status | Details |
|---|---|---|
| **MockLLM** | ✅ | Deterministic testing, no keys |
| **Anthropic Claude** | ✅ | Recommended for reasoning |
| **OpenAI GPT** | ✅ | High performance |
| **Google Gemini** | ✅ | Multimodal |
| **xAI Grok** | ✅ | Latest frontier |
| **Hugging Face** | ✅ | Open-source, local models |
| **Azure OpenAI** | ✅ | Enterprise deployment |
| **Token tracking** | ✅ | Automatic per-task |
| **Tool use** | ✅ | Function calling |
| **Multi-provider** | ✅ | Mix providers per skill |

---

## Next Steps

1. Pick a provider and install: `pip install agentic-workflow-orchestrator[llm-anthropic]`
2. Set API key in environment: `export ANTHROPIC_API_KEY="..."`
3. Create a skill that uses LLM: See examples in `examples/03_llm_content_review.py`
4. Track token usage in reports: `report.totals.llm_tokens_in`

**LLM is a tool for skills, not for orchestration. Use it wisely!** 🚀
