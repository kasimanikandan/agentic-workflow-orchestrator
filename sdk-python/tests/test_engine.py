"""Behavioral tests for the reference engine. Run: python3 tests/test_engine.py"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator import Orchestrator, Registry, Workflow  # noqa: E402


def _wf(tasks, **wf):
    return Workflow.from_dict({"workflow": {"name": "t", "tasks": tasks, **wf}})


def test_parallel_faster_than_sequential():
    reg = Registry()

    @reg.skill("sleep")
    async def sleep(ctx, inputs):
        await asyncio.sleep(0.2)
        return ctx.inputs.get("n")

    wf = _wf([
        {"id": "a", "skill": "sleep", "inputs": {"n": 1}},
        {"id": "b", "skill": "sleep", "inputs": {"n": 2}},
        {"id": "c", "skill": "sleep", "inputs": {"n": 3}},
    ], concurrency={"max_parallel": 3})

    t0 = time.monotonic()
    rep = Orchestrator(reg).run_sync(wf)
    elapsed = time.monotonic() - t0
    assert rep.status == "succeeded"
    assert elapsed < 0.4, f"expected parallel ~0.2s, got {elapsed:.2f}s"
    print(f"  parallel 3x200ms ran in {elapsed*1000:.0f}ms (OK)")


def test_concurrency_limit_serializes():
    reg = Registry()

    @reg.skill("sleep")
    async def sleep(ctx, inputs):
        await asyncio.sleep(0.15)
        return True

    wf = _wf([
        {"id": "a", "skill": "sleep"},
        {"id": "b", "skill": "sleep"},
    ], concurrency={"max_parallel": 1})  # force serial

    t0 = time.monotonic()
    Orchestrator(reg).run_sync(wf)
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.3, f"expected serial >=0.3s, got {elapsed:.2f}s"
    print(f"  max_parallel=1 serialized 2x150ms into {elapsed*1000:.0f}ms (OK)")


def test_rate_limit_throttles():
    reg = Registry()

    @reg.skill("noop")
    def noop(ctx, inputs):
        return 1

    # 5 req per 1s, 5 tasks => the 5th waits ~0.8s for refill.
    wf = _wf(
        [{"id": f"t{i}", "skill": "noop"} for i in range(5)],
        concurrency={"max_parallel": 10, "rate_limit": {"requests": 5, "per": "1s"}},
    )
    # capacity=5 means first 5 pass instantly; add a 6th to force a wait.
    wf = _wf(
        [{"id": f"t{i}", "skill": "noop"} for i in range(6)],
        concurrency={"max_parallel": 10, "rate_limit": {"requests": 5, "per": "1s"}},
    )
    t0 = time.monotonic()
    rep = Orchestrator(reg).run_sync(wf)
    elapsed = time.monotonic() - t0
    assert rep.status == "succeeded"
    assert elapsed >= 0.15, f"expected throttle delay, got {elapsed:.2f}s"
    print(f"  6 tasks @ 5/s throttled to {elapsed*1000:.0f}ms (OK)")


def test_retry_then_succeed():
    reg = Registry()
    attempts = {"n": 0}

    @reg.skill("flaky")
    def flaky(ctx, inputs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    wf = _wf([{"id": "a", "skill": "flaky", "retry": {"max": 3, "backoff": "none"}}])
    rep = Orchestrator(reg).run_sync(wf)
    assert rep.status == "succeeded"
    span = rep.tasks[0]
    assert span.attempts == 3, span.attempts
    assert rep.totals.retries == 2
    print(f"  flaky task succeeded on attempt {span.attempts}, retries={rep.totals.retries} (OK)")


def test_fail_fast_skips_downstream():
    reg = Registry()

    @reg.skill("boom")
    def boom(ctx, inputs):
        raise ValueError("nope")

    @reg.skill("ok")
    def ok(ctx, inputs):
        return 1

    wf = _wf([
        {"id": "a", "skill": "boom"},
        {"id": "b", "skill": "ok", "depends_on": ["a"]},
    ], defaults={"on_error": "fail_fast"})
    rep = Orchestrator(reg).run_sync(wf)
    assert rep.status == "failed"
    by_id = {t.id: t for t in rep.tasks}
    assert by_id["a"].status == "failed"
    assert by_id["b"].status == "skipped"
    assert rep.errors
    print(f"  fail_fast: a=failed, b=skipped, error={rep.errors[0]!r} (OK)")


def test_continue_on_error_isolates_branch():
    reg = Registry()

    @reg.skill("boom")
    def boom(ctx, inputs):
        raise ValueError("nope")

    @reg.skill("ok")
    def ok(ctx, inputs):
        return 1

    wf = _wf([
        {"id": "a", "skill": "boom", "on_error": "continue"},
        {"id": "b", "skill": "ok", "depends_on": ["a"]},  # skipped (upstream failed)
        {"id": "c", "skill": "ok"},                        # independent -> still runs
    ])
    rep = Orchestrator(reg).run_sync(wf)
    by_id = {t.id: t for t in rep.tasks}
    assert by_id["a"].status == "failed"
    assert by_id["b"].status == "skipped"
    assert by_id["c"].status == "succeeded"
    print("  continue: failed branch isolated, independent task c succeeded (OK)")


def test_cycle_rejected():
    try:
        _wf([
            {"id": "a", "skill": "x", "depends_on": ["b"]},
            {"id": "b", "skill": "x", "depends_on": ["a"]},
        ])
    except Exception as exc:  # noqa: BLE001
        assert "cycle" in str(exc).lower()
        print("  cyclic spec rejected at validation (OK)")
        return
    raise AssertionError("expected cycle to be rejected")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"running {len(tests)} tests\n")
    for fn in tests:
        print(f"- {fn.__name__}")
        fn()
    print(f"\nall {len(tests)} tests passed")
