"""Skill and tool registries + the SkillContext passed to handlers."""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from .llm import LlmProvider, LlmResult
from .report import Decision, LlmUsage

SkillHandler = Callable[["SkillContext", Dict[str, Any]], Any]  # may be sync or async


class Registry:
    """Holds skill and tool handlers, keyed by name."""

    def __init__(self) -> None:
        self._skills: Dict[str, SkillHandler] = {}
        self._tools: Dict[str, Callable[..., Any]] = {}

    def skill(self, name: str) -> Callable[[SkillHandler], SkillHandler]:
        def deco(fn: SkillHandler) -> SkillHandler:
            self._skills[name] = fn
            return fn
        return deco

    def add_skill(self, name: str, fn: SkillHandler) -> None:
        self._skills[name] = fn

    def tool(self, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._tools[name] = fn
            return fn
        return deco

    def add_tool(self, name: str, fn: Callable[..., Any]) -> None:
        self._tools[name] = fn

    def get_skill(self, name: str) -> SkillHandler:
        if name not in self._skills:
            raise KeyError(f"no skill registered for {name!r}")
        return self._skills[name]

    def get_tool(self, name: str) -> Callable[..., Any]:
        if name not in self._tools:
            raise KeyError(f"no tool registered for {name!r}")
        return self._tools[name]

    def has_skill(self, name: str) -> bool:
        return name in self._skills


class SkillContext:
    """Bridge passed to every skill handler — its connection back to the engine."""

    def __init__(
        self,
        *,
        run_id: str,
        task_id: str,
        inputs: Dict[str, Any],
        attempt: int,
        registry: Registry,
        llm_provider: Optional[LlmProvider],
        on_tool_call: Callable[[], None],
    ) -> None:
        self.run_id = run_id
        self.task_id = task_id
        self.inputs = inputs
        self.attempt = attempt
        self.cancelled = False
        self._registry = registry
        self._llm = llm_provider
        self._on_tool_call = on_tool_call
        self._start = time.monotonic()
        self.decisions: List[Decision] = []
        self.llm_usage: Optional[LlmUsage] = None
        self.tool_calls = 0
        self.logs: List[str] = []

    def log(self, message: str) -> None:
        self.logs.append(message)

    def record_decision(self, summary: str, rationale: Optional[str] = None, data: Optional[dict] = None) -> None:
        at_ms = int((time.monotonic() - self._start) * 1000)
        self.decisions.append(Decision(at_ms=at_ms, summary=summary, rationale=rationale, data=data))

    def call_tool(self, name: str, **kwargs: Any) -> Any:
        self.tool_calls += 1
        self._on_tool_call()
        return self._registry.get_tool(name)(**kwargs)

    def llm(self, messages, tools=None, model=None, **opts) -> LlmResult:
        if self._llm is None:
            raise RuntimeError("no LLM provider configured on the Orchestrator")
        result = self._llm.complete(messages, tools=tools, model=model, **opts)
        prev_in = self.llm_usage.tokens_in if self.llm_usage else 0
        prev_out = self.llm_usage.tokens_out if self.llm_usage else 0
        self.llm_usage = LlmUsage(
            provider=result.provider,
            model=result.model,
            tokens_in=prev_in + result.tokens_in,
            tokens_out=prev_out + result.tokens_out,
        )
        return result
