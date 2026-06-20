# LLM Providers — Complete Summary

**All major LLM providers are now supported in agentic-workflow-orchestrator v0.1.0**

---

## Quick Install

### All Providers
```bash
pip install agentic-workflow-orchestrator[llm]
```

### Individual Providers
```bash
pip install agentic-workflow-orchestrator[llm-anthropic]    # Claude
pip install agentic-workflow-orchestrator[llm-openai]       # GPT
pip install agentic-workflow-orchestrator[llm-gemini]       # Gemini
pip install agentic-workflow-orchestrator[llm-xai]          # Grok
pip install agentic-workflow-orchestrator[llm-huggingface]  # Local/HF
pip install agentic-workflow-orchestrator[llm-azure]        # Azure
```

---

## Provider Details

### 1. MockLLM — Testing & Demo
**No installation needed, built-in**

```python
from orchestrator import MockLLM

llm = MockLLM()
result = llm.complete(messages=[...])
# Returns: deterministic sentiment (positive/negative)
# Cost: FREE
# Latency: <1ms
# API key: None required
```

**Best for:** Development, testing, CI/CD, examples
**Models:** Deterministic classifier only
**Cost:** Free

---

### 2. Anthropic (Claude) — Recommended for Reasoning
**Requires: `pip install agentic-workflow-orchestrator[llm-anthropic]`**

```python
from orchestrator import AnthropicProvider

llm = AnthropicProvider(model="claude-opus-4-8")
# Or: claude-sonnet-4-6, claude-haiku-4-5

result = llm.complete(
    messages=[{"role": "user", "content": "..."}],
    tools=[...],  # Supports function calling
    model="claude-opus-4-8"
)
```

**Best for:** Complex reasoning, tool use, long context
**Models:**
- `claude-opus-4-8` — Best reasoning (slow, expensive)
- `claude-sonnet-4-6` — Balanced (recommended default)
- `claude-haiku-4-5` — Fast & cheap (simple tasks)

**Environment:** `ANTHROPIC_API_KEY`
**Cost:** High (Opus) → Low (Haiku)
**Documentation:** https://docs.anthropic.com

---

### 3. OpenAI (GPT) — High Performance
**Requires: `pip install agentic-workflow-orchestrator[llm-openai]`**

```python
from orchestrator import OpenAIProvider

llm = OpenAIProvider(model="gpt-4")
# Or: gpt-4-turbo, gpt-3.5-turbo

result = llm.complete(
    messages=[{"role": "user", "content": "..."}],
    tools=[...],  # Supports function calling
)
```

**Best for:** Fast responses, broad capability
**Models:**
- `gpt-4` — Best performance
- `gpt-4-turbo` — Better speed/cost ratio
- `gpt-3.5-turbo` — Fast & cheap

**Environment:** `OPENAI_API_KEY`
**Cost:** Moderate
**Documentation:** https://platform.openai.com/docs

---

### 4. Google Gemini — Multimodal
**Requires: `pip install agentic-workflow-orchestrator[llm-gemini]`**

```python
from orchestrator import GeminiProvider

llm = GeminiProvider(model="gemini-1.5-pro")
# Or: gemini-pro, gemini-pro-vision

result = llm.complete(
    messages=[{"role": "user", "content": "..."}],
)
```

**Best for:** Multimodal tasks, competitive pricing
**Models:**
- `gemini-1.5-pro` — Latest, best performance
- `gemini-pro` — Previous generation
- `gemini-pro-vision` — Vision-specific

**Environment:** `GOOGLE_API_KEY`
**Cost:** Moderate
**Documentation:** https://ai.google.dev

---

### 5. xAI (Grok) — Frontier Model
**Requires: `pip install agentic-workflow-orchestrator[llm-xai]`**

```python
from orchestrator import XAIProvider

llm = XAIProvider(model="grok-beta")

result = llm.complete(
    messages=[{"role": "user", "content": "..."}],
)
```

**Best for:** Cutting-edge reasoning, frontier capabilities
**Models:**
- `grok-beta` — Latest xAI frontier model

**Environment:** `XAI_API_KEY` (custom setup needed)
**Cost:** Competitive
**Documentation:** https://x.ai/api

---

### 6. Hugging Face — Open Source & Local
**Requires: `pip install agentic-workflow-orchestrator[llm-huggingface]`**

**Option A: Local execution**
```python
from orchestrator import HuggingFaceProvider

llm = HuggingFaceProvider(model="meta-llama/Llama-2-7b-chat-hf")
# Download ~13GB, runs locally
```

**Option B: Hugging Face Inference API**
```python
llm = HuggingFaceProvider(
    model="meta-llama/Llama-2-7b-chat-hf",
    api_key="hf_..."  # Hugging Face API token
)
```

**Best for:** Open-source models, cost control, privacy
**Models:**
- `meta-llama/Llama-2-7b-chat-hf` — Meta Llama 2
- `mistral-7b` — Mistral AI
- Any Hugging Face model

**Environment:** `HUGGINGFACEHUB_API_TOKEN` (for API mode)
**Cost:** Free (local) or nominal (API)
**Documentation:** https://huggingface.co/docs

---

### 7. Azure OpenAI — Enterprise
**Requires: `pip install agentic-workflow-orchestrator[llm-azure]`**

```python
from orchestrator import AzureOpenAIProvider

llm = AzureOpenAIProvider(
    deployment_name="my-gpt4-deployment",
    api_key="your-azure-key",
    azure_endpoint="https://my-org.openai.azure.com/",
    api_version="2024-02-01"
)

result = llm.complete(
    messages=[{"role": "user", "content": "..."}],
)
```

**Best for:** Enterprise deployments, compliance, private cloud
**Models:** Same as OpenAI (gpt-4, gpt-3.5-turbo, etc.)
**Environment:** `AZURE_OPENAI_KEY`, `AZURE_OPENAI_ENDPOINT`
**Cost:** Managed by Azure
**Documentation:** https://learn.microsoft.com/en-us/azure/ai-services/openai/

---

## Provider Comparison

| Provider | Speed | Cost | Reasoning | Multimodal | Tool Use | Status |
|---|---|---|---|---|---|---|
| **MockLLM** | ⚡⚡⚡ | FREE | Basic | ❌ | ❌ | ✅ |
| **Claude (Opus)** | ⚡ | $$$ | ⭐⭐⭐ | ❌ | ✅ | ✅ |
| **Claude (Sonnet)** | ⚡⚡ | $$ | ⭐⭐⭐ | ❌ | ✅ | ✅ |
| **Claude (Haiku)** | ⚡⚡⚡ | $ | ⭐⭐ | ❌ | ✅ | ✅ |
| **GPT-4** | ⚡⚡ | $$$ | ⭐⭐⭐ | ✅ | ✅ | ✅ |
| **GPT-4 Turbo** | ⚡⚡ | $$ | ⭐⭐⭐ | ✅ | ✅ | ✅ |
| **GPT-3.5** | ⚡⚡⚡ | $ | ⭐⭐ | ❌ | ✅ | ✅ |
| **Gemini 1.5 Pro** | ⚡⚡ | $$ | ⭐⭐⭐ | ✅ | ❌ | ✅ |
| **Grok** | ⚡⚡ | $$ | ⭐⭐⭐ | ❌ | ✅ | ✅ |
| **Llama 2** | ⚡ (local) | FREE | ⭐⭐ | ❌ | ❌ | ✅ |
| **Azure GPT-4** | ⚡⚡ | $$ | ⭐⭐⭐ | ✅ | ✅ | ✅ |

---

## Usage Pattern

**Every skill can independently choose an LLM provider:**

```python
from orchestrator import Registry, MockLLM, AnthropicProvider, OpenAIProvider

registry = Registry()

@registry.skill("task1")
def task1(ctx, inputs):
    # Use Claude
    result = ctx.llm(messages=[...], model="claude-opus-4-8")
    return {"output": result.text}

@registry.skill("task2")
def task2(ctx, inputs):
    # Use GPT-3.5 (cheaper, faster)
    openai = OpenAIProvider(model="gpt-3.5-turbo")
    result = openai.complete(messages=[...])
    return {"output": result.text}

@registry.skill("task3")
def task3(ctx, inputs):
    # Use MockLLM (testing)
    mock = MockLLM()
    result = mock.complete(messages=[...])
    return {"output": result.text}
```

---

## Token Tracking

All LLM usage is automatically tracked:

```python
report = orch.run_sync(workflow, inputs)

# Per-task breakdown
for task in report.tasks:
    if task.llm_usage:
        print(f"{task.name}:")
        print(f"  Model: {task.llm_usage.model}")
        print(f"  Provider: {task.llm_usage.provider}")
        print(f"  Tokens in: {task.llm_usage.tokens_in}")
        print(f"  Tokens out: {task.llm_usage.tokens_out}")

# Workflow-level summary
print(f"Total tokens in: {report.totals.llm_tokens_in}")
print(f"Total tokens out: {report.totals.llm_tokens_out}")
```

---

## Cost Optimization Tips

1. **Use cheaper models for simple tasks:**
   ```python
   # Simple classification → use Haiku or GPT-3.5
   result = ctx.llm(messages=[...], model="claude-haiku-4-5")
   ```

2. **Use expensive models for complex reasoning:**
   ```python
   # Complex analysis → use Opus or GPT-4
   result = ctx.llm(messages=[...], model="claude-opus-4-8")
   ```

3. **Batch requests:**
   ```python
   # Classify 100 items in one LLM call (not 100 calls)
   result = ctx.llm(
       messages=[{"role": "user", "content": f"Classify all: {items}"}],
   )
   ```

4. **Cache results:**
   ```python
   cache = {}
   if text not in cache:
       result = ctx.llm(messages=[...])
       cache[text] = result.text
   ```

5. **Use local models (Llama, Mistral):**
   ```python
   # Free after initial download
   llm = HuggingFaceProvider(model="meta-llama/Llama-2-7b-chat-hf")
   ```

---

## Documentation & Examples

| Resource | Location |
|---|---|
| **LLM Integration Guide** | `LLM_INTEGRATION.md` |
| **Why NOT for orchestration** | `LLM_NOT_FOR_ORCHESTRATION.md` |
| **Multi-provider example** | `examples/05_multi_provider_llm.py` |
| **Content classification** | `examples/03_llm_content_review.py` |
| **Architecture docs** | `DESIGN.md` § 7 |

---

## Quick Start

```bash
# 1. Install
pip install agentic-workflow-orchestrator[llm]

# 2. Create skill that uses LLM
from orchestrator import Registry, AnthropicProvider

registry = Registry()

@registry.skill("nlp.sentiment")
def sentiment(ctx, inputs):
    result = ctx.llm(
        messages=[{"role": "user", "content": inputs["text"]}],
        model="claude-haiku-4-5",
    )
    return {"sentiment": result.text}

# 3. Run workflow
from orchestrator import Orchestrator, Workflow

orch = Orchestrator(registry, llm=AnthropicProvider())
report = orch.run_sync(workflow, inputs={})

# 4. Track usage
print(f"Total tokens: {report.totals.llm_tokens_in + report.totals.llm_tokens_out}")
```

---

## Summary

✅ **7 providers available:**
- MockLLM (deterministic)
- Anthropic Claude (reasoning)
- OpenAI GPT (performance)
- Google Gemini (multimodal)
- xAI Grok (frontier)
- Hugging Face (open-source)
- Azure OpenAI (enterprise)

✅ **Each skill chooses its own provider**

✅ **All usage automatically tracked**

✅ **Zero required dependencies** (LLM is optional)

✅ **Individual or bundle installation**

🚀 **Ready to build intelligent workflows!**
