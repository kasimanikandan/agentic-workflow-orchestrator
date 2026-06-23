"""Multi-agent workflow orchestration SDK — Python reference implementation.

Quick start:

    from orchestrator import Workflow, Orchestrator, Registry, MockLLM

    reg = Registry()

    @reg.skill("market.fetch")
    def fetch(ctx, inputs):
        ctx.record_decision("selected primary feed", rationale="lowest latency")
        return {"ticker": inputs["ticker"], "last": 199.4}

    wf = Workflow.from_file("spec/examples/market-analysis.json")
    report = Orchestrator(reg, llm=MockLLM()).run_sync(wf, {"ticker": "AAPL"})
    print(report.to_json())
"""
from .engine import Orchestrator, TaskFailed, get_engine_path
from .llm import (
    AnthropicProvider,
    AzureOpenAIProvider,
    GeminiProvider,
    HuggingFaceProvider,
    LlmProvider,
    LlmResult,
    MockLLM,
    OpenAIProvider,
    XAIProvider,
)
from .ratelimit import TokenBucket
from .registry import Registry, SkillContext
from .report import Decision, LlmUsage, Report, TaskSpan, Totals
from .spec import RateLimit, Retry, SpecError, Task, Workflow, resolve_template

__all__ = [
    "Orchestrator",
    "TaskFailed",
    "get_engine_path",
    "Registry",
    "SkillContext",
    "Workflow",
    "Task",
    "RateLimit",
    "Retry",
    "SpecError",
    "resolve_template",
    "Report",
    "TaskSpan",
    "Decision",
    "LlmUsage",
    "Totals",
    "LlmProvider",
    "LlmResult",
    "MockLLM",
    "AnthropicProvider",
    "OpenAIProvider",
    "GeminiProvider",
    "XAIProvider",
    "HuggingFaceProvider",
    "AzureOpenAIProvider",
    "TokenBucket",
]

__version__ = "0.1.0"
