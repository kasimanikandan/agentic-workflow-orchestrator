"""Workflow spec: parsing, validation and template resolution.

Language-neutral template -> typed objects. Mirrors spec/spec.schema.json.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_DURATION_RE = re.compile(r"^(\d+)(ms|s|m|h)$")
_TEMPLATE_RE = re.compile(r"\$\{([^}]+)\}")
_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_duration(text: Optional[str], default: Optional[float] = None) -> Optional[float]:
    """'500ms' -> 0.5 seconds. None/absent -> default."""
    if text is None:
        return default
    m = _DURATION_RE.match(str(text).strip())
    if not m:
        raise SpecError(f"invalid duration: {text!r}")
    return int(m.group(1)) * _UNITS[m.group(2)]


class SpecError(ValueError):
    """Raised when a spec is structurally invalid."""


@dataclass
class RateLimit:
    requests: int
    per: float  # seconds
    tokens: Optional[int] = None
    per_tokens: Optional[float] = None

    @staticmethod
    def from_dict(d: Optional[dict]) -> "Optional[RateLimit]":
        if not d:
            return None
        return RateLimit(
            requests=int(d["requests"]),
            per=parse_duration(d["per"]),
            tokens=d.get("tokens"),
            per_tokens=parse_duration(d.get("per_tokens")),
        )


@dataclass
class Retry:
    max: int = 0
    backoff: str = "exponential"
    base: float = 0.5
    jitter: bool = True

    @staticmethod
    def from_dict(d: Optional[dict]) -> "Optional[Retry]":
        if not d:
            return None
        return Retry(
            max=int(d.get("max", 0)),
            backoff=d.get("backoff", "exponential"),
            base=parse_duration(d.get("base"), 0.5),
            jitter=bool(d.get("jitter", True)),
        )


@dataclass
class Provider:
    name: str
    rate_limit: Optional[RateLimit] = None


@dataclass
class Task:
    id: str
    skill: str
    provider: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    inputs: Dict[str, Any] = field(default_factory=dict)
    retry: Optional[Retry] = None
    timeout: Optional[float] = None
    on_error: Optional[str] = None
    idempotent: bool = False


@dataclass
class Workflow:
    name: str
    tasks: List[Task]
    version: int = 1
    max_parallel: int = 8
    rate_limit: Optional[RateLimit] = None
    providers: Dict[str, Provider] = field(default_factory=dict)
    default_retry: Optional[Retry] = None
    default_timeout: Optional[float] = None
    default_on_error: str = "fail_fast"
    inputs_schema: Dict[str, dict] = field(default_factory=dict)
    output: Optional[str] = None

    # ---- loaders ----
    @staticmethod
    def from_dict(doc: dict) -> "Workflow":
        wf = doc.get("workflow")
        if not isinstance(wf, dict):
            raise SpecError("missing top-level 'workflow' object")

        conc = wf.get("concurrency", {}) or {}
        defaults = wf.get("defaults", {}) or {}
        providers = {
            name: Provider(name, RateLimit.from_dict((p or {}).get("rate_limit")))
            for name, p in (wf.get("providers", {}) or {}).items()
        }
        tasks = [
            Task(
                id=t["id"],
                skill=t["skill"],
                provider=t.get("provider"),
                depends_on=list(t.get("depends_on", []) or []),
                inputs=dict(t.get("inputs", {}) or {}),
                retry=Retry.from_dict(t.get("retry")),
                timeout=parse_duration(t.get("timeout")),
                on_error=t.get("on_error"),
                idempotent=bool(t.get("idempotent", False)),
            )
            for t in wf.get("tasks", [])
        ]
        model = Workflow(
            name=wf["name"],
            version=int(wf.get("version", 1)),
            tasks=tasks,
            max_parallel=int(conc.get("max_parallel", 8)),
            rate_limit=RateLimit.from_dict(conc.get("rate_limit")),
            providers=providers,
            default_retry=Retry.from_dict(defaults.get("retry")) or Retry(),
            default_timeout=parse_duration(defaults.get("timeout")),
            default_on_error=defaults.get("on_error", "fail_fast"),
            inputs_schema=wf.get("inputs", {}) or {},
            output=wf.get("output"),
        )
        model.validate()
        return model

    @staticmethod
    def from_json(text: str) -> "Workflow":
        return Workflow.from_dict(json.loads(text))

    @staticmethod
    def from_file(path: str) -> "Workflow":
        with open(path, "r") as fh:
            text = fh.read()
        if path.endswith((".yaml", ".yml")):
            try:
                import yaml  # optional dependency
            except ImportError as exc:  # pragma: no cover
                raise SpecError(
                    "PyYAML is required to load .yaml specs; use a .json spec or `pip install pyyaml`"
                ) from exc
            return Workflow.from_dict(yaml.safe_load(text))
        return Workflow.from_json(text)

    # ---- validation ----
    def validate(self) -> "Workflow":
        ids = [t.id for t in self.tasks]
        if len(ids) != len(set(ids)):
            raise SpecError("duplicate task ids")
        idset = set(ids)
        for t in self.tasks:
            for dep in t.depends_on:
                if dep not in idset:
                    raise SpecError(f"task {t.id!r} depends on unknown task {dep!r}")
            if t.provider and t.provider not in self.providers:
                raise SpecError(f"task {t.id!r} references unknown provider {t.provider!r}")
        self._assert_acyclic()
        return self

    def _assert_acyclic(self) -> None:
        graph = {t.id: list(t.depends_on) for t in self.tasks}
        WHITE, GREY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in graph}

        def visit(node: str) -> None:
            color[node] = GREY
            for dep in graph[node]:
                if color[dep] == GREY:
                    raise SpecError(f"dependency cycle detected at {node!r} -> {dep!r}")
                if color[dep] == WHITE:
                    visit(dep)
            color[node] = BLACK

        for tid in graph:
            if color[tid] == WHITE:
                visit(tid)

    def task_map(self) -> Dict[str, Task]:
        return {t.id: t for t in self.tasks}


def resolve_template(value: Any, scope: Dict[str, Any]) -> Any:
    """Resolve ${...} references against a scope dict.

    Supported paths: input.<field>, <taskId>.output, <taskId>.output.<field...>.
    A string that is exactly one reference returns the referenced value (preserving
    its type); otherwise references are substituted as text within the string.
    """
    if isinstance(value, dict):
        return {k: resolve_template(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_template(v, scope) for v in value]
    if not isinstance(value, str):
        return value

    full = _TEMPLATE_RE.fullmatch(value.strip())
    if full:
        return _lookup(full.group(1).strip(), scope)

    def repl(m: "re.Match[str]") -> str:
        v = _lookup(m.group(1).strip(), scope)
        return v if isinstance(v, str) else json.dumps(v)

    return _TEMPLATE_RE.sub(repl, value)


def _lookup(path: str, scope: Dict[str, Any]) -> Any:
    parts = path.split(".")
    node: Any = scope
    for p in parts:
        if isinstance(node, dict) and p in node:
            node = node[p]
        else:
            raise SpecError(f"unresolved template reference: ${{{path}}}")
    return node
