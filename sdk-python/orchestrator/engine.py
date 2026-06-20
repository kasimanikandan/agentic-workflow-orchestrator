"""The orchestration engine: DAG scheduler with concurrency + rate limiting.

This is the Python reference implementation. It runs workflows in-process and
defines the canonical scheduling/report semantics that the Go engine and other
SDKs must reproduce against the shared conformance fixtures.
"""
from __future__ import annotations

import asyncio
import inspect
import random
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .llm import LlmProvider
from .ratelimit import NullBucket, bucket_for, token_bucket_for
from .registry import Registry, SkillContext
from .report import Report, TaskSpan, Totals, compute_critical_path
from .spec import Retry, Task, Workflow, resolve_template


class TaskFailed(Exception):
    def __init__(self, task_id: str, message: str):
        super().__init__(f"task {task_id!r} failed: {message}")
        self.task_id = task_id
        self.message = message


class Orchestrator:
    """Embedded engine. Construct with a Registry and (optionally) an LLM provider."""

    def __init__(self, registry: Registry, llm: Optional[LlmProvider] = None):
        self.registry = registry
        self.llm = llm

    def run_sync(self, workflow: Workflow, inputs: Optional[Dict[str, Any]] = None) -> Report:
        return asyncio.run(self.run(workflow, inputs))

    async def run(self, workflow: Workflow, inputs: Optional[Dict[str, Any]] = None) -> Report:
        inputs = inputs or {}
        self._validate_inputs(workflow, inputs)
        run_id = "r_" + uuid.uuid4().hex[:16]
        started_wall = datetime.now(timezone.utc)
        t0 = time.monotonic()

        task_map = workflow.task_map()
        children: Dict[str, List[str]] = defaultdict(list)
        indeg: Dict[str, int] = {}
        for t in workflow.tasks:
            indeg[t.id] = len(t.depends_on)
            for dep in t.depends_on:
                children[dep].append(t.id)

        # Rate buckets: one global, one per provider.
        global_bucket = bucket_for(workflow.rate_limit, "global")
        prov_req = {n: bucket_for(p.rate_limit, f"{n}.req") for n, p in workflow.providers.items()}
        prov_tok = {n: token_bucket_for(p.rate_limit, f"{n}.tok") for n, p in workflow.providers.items()}

        sem = asyncio.Semaphore(workflow.max_parallel)

        results: Dict[str, Any] = {}
        spans: Dict[str, TaskSpan] = {}
        totals = Totals()

        ready: List[str] = [t.id for t in workflow.tasks if indeg[t.id] == 0]
        skipped: set = set()
        running: Dict[asyncio.Task, str] = {}
        run_failed = False
        first_error: Optional[str] = None

        def mark_descendants_skipped(start: str) -> None:
            stack = list(children[start])
            while stack:
                cid = stack.pop()
                if cid in skipped or cid in spans:
                    continue
                skipped.add(cid)
                spans[cid] = TaskSpan(id=cid, status="skipped")
                stack.extend(children[cid])

        while ready or running:
            while ready:
                tid = ready.pop(0)
                if tid in skipped:
                    continue
                coro = self._execute_task(
                    workflow, task_map[tid], run_id, results, sem,
                    global_bucket, prov_req, prov_tok,
                )
                running[asyncio.ensure_future(coro)] = tid

            if not running:
                break

            done, _ = await asyncio.wait(running.keys(), return_when=asyncio.FIRST_COMPLETED)
            for fut in done:
                tid = running.pop(fut)
                span: TaskSpan = fut.result()  # _execute_task never raises
                spans[tid] = span
                totals.retries += max(0, span.attempts - 1)
                if span.llm:
                    totals.llm_tokens_in += span.llm.tokens_in
                    totals.llm_tokens_out += span.llm.tokens_out
                totals.tool_calls += getattr(span, "_tool_calls", 0)

                if span.status == "succeeded":
                    results[tid] = span.output
                    for c in children[tid]:
                        indeg[c] -= 1
                        if indeg[c] == 0 and c not in skipped:
                            ready.append(c)
                else:  # failed
                    if first_error is None:
                        first_error = span.error
                    on_error = task_map[tid].on_error or workflow.default_on_error
                    if on_error == "fail_fast":
                        run_failed = True
                        for f in list(running.keys()):
                            f.cancel()
                        if running:
                            await asyncio.wait(running.keys())
                        running.clear()
                        ready.clear()
                        # Everything not yet terminal is skipped.
                        for other in task_map:
                            if other not in spans:
                                spans[other] = TaskSpan(id=other, status="skipped")
                        break
                    else:
                        mark_descendants_skipped(tid)
            if run_failed:
                break

        depends_on = {t.id: t.depends_on for t in workflow.tasks}
        status = "failed" if (run_failed or any(s.status == "failed" for s in spans.values())) else "succeeded"
        output = None
        if status == "succeeded" and workflow.output:
            scope = {"input": inputs, **{tid: {"output": out} for tid, out in results.items()}}
            try:
                output = resolve_template(workflow.output, scope)
            except Exception:  # noqa: BLE001 - output is best-effort
                output = None

        ordered = [spans[t.id] for t in workflow.tasks if t.id in spans]
        return Report(
            workflow=workflow.name,
            run_id=run_id,
            status=status,
            started_at=started_wall.isoformat(),
            duration_ms=int((time.monotonic() - t0) * 1000),
            tasks=ordered,
            critical_path=compute_critical_path(spans, depends_on),
            totals=totals,
            errors=[first_error] if first_error else [],
            output=output,
        )

    async def _execute_task(
        self, workflow, task: Task, run_id, results, sem,
        global_bucket, prov_req, prov_tok,
    ) -> TaskSpan:
        retry = task.retry or workflow.default_retry or Retry()
        timeout = task.timeout if task.timeout is not None else workflow.default_timeout
        # Resolve template refs against run inputs + outputs of completed deps.
        scope = {"input": self._current_inputs, **{tid: {"output": out} for tid, out in results.items()}}
        resolved_inputs = resolve_template(task.inputs, scope)

        span = TaskSpan(id=task.id, status="failed", attempts=0)
        t_task = time.monotonic()
        last_err = "unknown error"

        for attempt in range(1, retry.max + 2):  # max retries => max+1 total attempts
            span.attempts = attempt
            ctx = SkillContext(
                run_id=run_id, task_id=task.id, inputs=resolved_inputs, attempt=attempt,
                registry=self.registry, llm_provider=self.llm,
                on_tool_call=lambda: None,
            )
            try:
                async with sem:
                    await global_bucket.acquire()
                    if task.provider:
                        await prov_req.get(task.provider, NullBucket()).acquire()
                    output = await self._invoke(task, ctx, timeout)
                span.status = "succeeded"
                span.output = output
                span.decisions = ctx.decisions
                span.llm = ctx.llm_usage
                span._tool_calls = ctx.tool_calls  # type: ignore[attr-defined]
                span.duration_ms = int((time.monotonic() - t_task) * 1000)
                return span
            except asyncio.TimeoutError:
                last_err = f"timeout after {timeout}s"
            except asyncio.CancelledError:
                span.status = "skipped"
                span.error = "cancelled"
                span.duration_ms = int((time.monotonic() - t_task) * 1000)
                return span
            except Exception as exc:  # noqa: BLE001
                last_err = f"{type(exc).__name__}: {exc}"
            span.decisions = ctx.decisions
            span.llm = ctx.llm_usage
            span._tool_calls = ctx.tool_calls  # type: ignore[attr-defined]
            if attempt <= retry.max:
                await asyncio.sleep(self._backoff(retry, attempt))

        span.status = "failed"
        span.error = last_err
        span.duration_ms = int((time.monotonic() - t_task) * 1000)
        return span

    async def _invoke(self, task: Task, ctx: SkillContext, timeout: Optional[float]) -> Any:
        handler = self.registry.get_skill(task.skill)
        if inspect.iscoroutinefunction(handler):
            coro = handler(ctx, ctx.inputs)
        else:
            loop = asyncio.get_event_loop()
            coro = loop.run_in_executor(None, lambda: handler(ctx, ctx.inputs))
        if timeout is not None:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro

    @staticmethod
    def _backoff(retry: Retry, attempt: int) -> float:
        if retry.backoff == "none":
            base = 0.0
        elif retry.backoff == "fixed":
            base = retry.base
        else:  # exponential
            base = retry.base * (2 ** (attempt - 1))
        if retry.jitter and base > 0:
            base *= 0.5 + random.random() / 2
        return base

    # --- inputs plumbing ---
    _current_inputs: Dict[str, Any] = {}

    def _validate_inputs(self, workflow: Workflow, inputs: Dict[str, Any]) -> None:
        self._current_inputs = inputs
        for name, schema in workflow.inputs_schema.items():
            if schema.get("required") and name not in inputs:
                raise ValueError(f"missing required input: {name!r}")
