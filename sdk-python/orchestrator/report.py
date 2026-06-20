"""Run report data model + critical-path computation."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Decision:
    at_ms: int
    summary: str
    rationale: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


@dataclass
class LlmUsage:
    provider: str
    model: str
    tokens_in: int
    tokens_out: int


@dataclass
class TaskSpan:
    id: str
    status: str  # succeeded | failed | skipped
    duration_ms: int = 0
    attempts: int = 0
    llm: Optional[LlmUsage] = None
    decisions: List[Decision] = field(default_factory=list)
    error: Optional[str] = None
    output: Any = None  # not serialized into the public report by default


@dataclass
class Totals:
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    tool_calls: int = 0
    retries: int = 0


@dataclass
class Report:
    workflow: str
    run_id: str
    status: str
    started_at: str
    duration_ms: int
    tasks: List[TaskSpan]
    critical_path: List[str]
    totals: Totals
    errors: List[str]
    output: Any = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "workflow": self.workflow,
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "tasks": [],
            "critical_path": self.critical_path,
            "totals": asdict(self.totals),
            "errors": self.errors,
            "output": self.output,
        }
        for t in self.tasks:
            td: Dict[str, Any] = {
                "id": t.id,
                "status": t.status,
                "duration_ms": t.duration_ms,
                "attempts": t.attempts,
            }
            if t.llm:
                td["llm"] = asdict(t.llm)
            if t.decisions:
                td["decisions"] = [asdict(x) for x in t.decisions]
            if t.error:
                td["error"] = t.error
            d["tasks"].append(td)
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


def compute_critical_path(spans: Dict[str, TaskSpan], depends_on: Dict[str, List[str]]) -> List[str]:
    """Longest path by cumulative duration through succeeded tasks (the bottleneck chain)."""
    best_cost: Dict[str, int] = {}
    best_prev: Dict[str, Optional[str]] = {}

    def cost(node: str) -> int:
        if node in best_cost:
            return best_cost[node]
        span = spans.get(node)
        own = span.duration_ms if span and span.status == "succeeded" else 0
        prev_best, prev_node = 0, None
        for dep in depends_on.get(node, []):
            if dep in spans and spans[dep].status == "succeeded":
                c = cost(dep)
                if c > prev_best:
                    prev_best, prev_node = c, dep
        best_cost[node] = own + prev_best
        best_prev[node] = prev_node
        return best_cost[node]

    succeeded = [tid for tid, s in spans.items() if s.status == "succeeded"]
    if not succeeded:
        return []
    end = max(succeeded, key=cost)
    chain: List[str] = []
    node: Optional[str] = end
    while node is not None:
        chain.append(node)
        node = best_prev.get(node)
    chain.reverse()
    return chain
