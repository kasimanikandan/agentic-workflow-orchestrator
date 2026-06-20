"""End-to-end test: Python SDK drives the compiled Go engine binary via stdio.

Spawns the binary as a subprocess, sends a start_run, handles skill_invocations
concurrently in threads (matching the engine's parallel dispatch), sends
skill_results back, and verifies the final report.

Run from the engine directory after `go build`:
    python3 ../../sdk-python/tests/test_go_engine.py ../engine/orchestrator
"""
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

DEFAULT_BIN = os.path.join(os.path.dirname(__file__), "../../engine/orchestrator")

MARKET_SPEC = {
    "workflow": {
        "name": "market-analysis",
        "concurrency": {"max_parallel": 4},
        "tasks": [
            {"id": "fetch_prices", "skill": "market.fetch", "inputs": {"ticker": "${input.ticker}"}},
            {"id": "fetch_news",   "skill": "news.fetch",   "inputs": {"ticker": "${input.ticker}"}},
            {"id": "sentiment",    "skill": "llm.classify", "depends_on": ["fetch_news"],
             "inputs": {"text": "${fetch_news.output}"}},
            {"id": "report",       "skill": "analysis.summarize",
             "depends_on": ["fetch_prices", "sentiment"],
             "inputs": {"prices": "${fetch_prices.output}", "sentiment": "${sentiment.output}"}},
        ],
        "output": "${report.output}",
    }
}

INPUTS = {"ticker": "AAPL"}


def default_skill(skill: str, inputs: dict):
    """Deterministic offline skill implementations used by most tests."""
    if skill == "market.fetch":
        return {"ticker": inputs["ticker"], "last": 199.4}
    if skill == "news.fetch":
        return "Company cuts full-year guidance; analysts flag a miss."
    if skill == "llm.classify":
        text = str(inputs.get("text", ""))
        neg = any(w in text.lower() for w in ("cut", "miss", "loss", "negative", "down"))
        return {"label": "net-negative" if neg else "net-positive", "confidence": 0.81}
    if skill == "analysis.summarize":
        prices = inputs["prices"]
        sentiment = inputs["sentiment"]
        return {
            "ticker": prices["ticker"],
            "last": prices["last"],
            "sentiment": sentiment["label"],
            "recommendation": "HOLD" if sentiment["label"] == "net-negative" else "BUY",
        }
    raise ValueError(f"unknown skill: {skill}")


# ---------------------------------------------------------------------------
# Engine driver
# ---------------------------------------------------------------------------

class EngineDriver:
    """Wraps the Go binary as a subprocess and speaks the NDJSON stdio protocol.

    Skill invocations are dispatched to a thread pool so multiple tasks run
    concurrently, matching the engine's parallel dispatch.
    """

    def __init__(self, binary: str, skill_fn=None):
        self.binary = binary
        self.skill_fn = skill_fn or default_skill
        self._write_lock = threading.Lock()
        self.events = []
        self.skills_handled = 0

    def run(self, spec: dict, inputs: dict) -> dict:
        self._proc = subprocess.Popen(
            [self.binary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._report = None

        self._write_raw({"type": "start_run",
                         "spec_json": json.dumps(spec),
                         "inputs_json": json.dumps(inputs)})

        with ThreadPoolExecutor(max_workers=16) as pool:
            while True:
                line = self._proc.stdout.readline()
                if not line:
                    stderr = self._proc.stderr.read().decode()
                    raise RuntimeError(f"engine exited early. stderr: {stderr}")

                msg = json.loads(line.strip())
                t = msg.get("type")

                if t == "event":
                    self.events.append(msg)
                elif t == "skill_invocation":
                    # Dispatch to thread so parallel tasks don't block each other.
                    pool.submit(self._handle_skill, msg)
                elif t == "report":
                    self._report = msg["report"]
                    break
                elif t == "error":
                    raise RuntimeError(f"engine error: {msg.get('error')}")

        self._proc.stdin.close()
        self._proc.wait()
        return self._report

    def _handle_skill(self, msg: dict):
        inv_id = msg["invocation_id"]
        skill  = msg["skill"]
        inputs = json.loads(msg["inputs_json"])

        output = error = None
        decisions = []
        try:
            result = self.skill_fn(skill, inputs)
            output = json.dumps(result)
            decisions = [{"at_ms": 1, "summary": f"completed {skill}"}]
            self.skills_handled += 1
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc), "retryable": False}

        self._write_raw({"type": "skill_result", "invocation_id": inv_id,
                         "output_json": output, "error": error, "decisions": decisions})

    def _write_raw(self, msg: dict):
        data = (json.dumps(msg) + "\n").encode()
        with self._write_lock:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_basic_run(binary):
    driver = EngineDriver(binary)
    rep = driver.run(MARKET_SPEC, INPUTS)

    assert rep["status"] == "succeeded", f"got {rep['status']}, errors={rep.get('errors')}"
    assert rep["workflow"] == "market-analysis"
    assert driver.skills_handled == 4, f"expected 4 skills, got {driver.skills_handled}"

    by_id = {t["id"]: t for t in rep["tasks"]}
    for tid in ["fetch_prices", "fetch_news", "sentiment", "report"]:
        assert by_id[tid]["status"] == "succeeded", f"{tid}: {by_id[tid]['status']}"

    output = rep.get("output") or {}
    assert output.get("recommendation") == "HOLD", f"output={output}"
    assert output.get("ticker") == "AAPL"

    cp = rep.get("critical_path") or []
    assert len(cp) > 0, "critical_path should not be empty"
    assert "report" in cp, f"report should be on the critical path, got {cp}"

    print(f"  status={rep['status']}, duration={rep['duration_ms']}ms, "
          f"output={output}, critical_path={' → '.join(cp)}")


def test_parallelism(binary):
    """fetch_prices and fetch_news share no deps — they must run in parallel."""
    DELAY_MS = 200
    spec = {
        "workflow": {
            "name": "parallel-test",
            "concurrency": {"max_parallel": 4},
            "tasks": [
                {"id": "a", "skill": "slow", "inputs": {}},
                {"id": "b", "skill": "slow", "inputs": {}},
                {"id": "c", "skill": "fast", "depends_on": ["a", "b"], "inputs": {}},
            ],
        }
    }

    def skill_fn(skill, inputs):
        if skill == "slow":
            time.sleep(DELAY_MS / 1000)
            return "done"
        return "fast"

    t0 = time.monotonic()
    rep = EngineDriver(binary, skill_fn=skill_fn).run(spec, {})
    elapsed_ms = (time.monotonic() - t0) * 1000

    assert rep["status"] == "succeeded", rep["status"]
    # Serial would be ~400ms. Parallel should be ~DELAY_MS + small overhead.
    assert elapsed_ms < DELAY_MS * 1.8, \
        f"expected parallel (~{DELAY_MS}ms), got {elapsed_ms:.0f}ms — tasks ran sequentially"
    print(f"  a∥b+c: {elapsed_ms:.0f}ms (threshold {DELAY_MS * 1.8:.0f}ms) ✓")


def test_fail_fast(binary):
    spec = {
        "workflow": {
            "name": "fail-test",
            "defaults": {"on_error": "fail_fast"},
            "tasks": [
                {"id": "boom",  "skill": "explode", "inputs": {}},
                {"id": "after", "skill": "ok",      "inputs": {}, "depends_on": ["boom"]},
            ],
        }
    }

    def skill_fn(skill, inputs):
        if skill == "explode":
            raise RuntimeError("kaboom")
        return "ok"

    rep = EngineDriver(binary, skill_fn=skill_fn).run(spec, {})
    assert rep["status"] == "failed", rep["status"]
    by_id = {t["id"]: t for t in rep["tasks"]}
    assert by_id["boom"]["status"]  == "failed",  by_id["boom"]["status"]
    assert by_id["after"]["status"] == "skipped", by_id["after"]["status"]
    print(f"  boom=failed, after=skipped ✓")


def test_retry(binary):
    spec = {
        "workflow": {
            "name": "retry-test",
            "tasks": [{"id": "flaky", "skill": "unstable", "inputs": {},
                        "retry": {"max": 3, "backoff": "none"}}],
        }
    }
    call_count = [0]

    # Subclass to send retryable=True on failures.
    class RetryDriver(EngineDriver):
        def _handle_skill(self, msg):
            call_count[0] += 1
            inv_id = msg["invocation_id"]
            output = error = None
            if call_count[0] < 3:
                error = {"type": "RuntimeError", "message": "transient", "retryable": True}
            else:
                output = '"ok"'
                self.skills_handled += 1
            self._write_raw({"type": "skill_result", "invocation_id": inv_id,
                              "output_json": output, "error": error, "decisions": []})

    rep = RetryDriver(binary).run(spec, {})
    assert rep["status"] == "succeeded", f"status={rep['status']} errors={rep.get('errors')}"
    span = rep["tasks"][0]
    assert span["attempts"] == 3, f"expected 3 attempts, got {span['attempts']}"
    assert rep["totals"]["retries"] == 2
    print(f"  succeeded on attempt {span['attempts']}, retries={rep['totals']['retries']} ✓")


def test_continue_on_error(binary):
    """Failed task with on_error=continue: downstream skipped, independent tasks run."""
    spec = {
        "workflow": {
            "name": "continue-test",
            "tasks": [
                {"id": "bad", "skill": "boom", "inputs": {}, "on_error": "continue"},
                {"id": "dep", "skill": "ok",   "inputs": {}, "depends_on": ["bad"]},
                {"id": "ind", "skill": "ok",   "inputs": {}},  # independent → still runs
            ],
        }
    }

    def skill_fn(skill, inputs):
        if skill == "boom":
            raise RuntimeError("nope")
        return "ok"

    rep = EngineDriver(binary, skill_fn=skill_fn).run(spec, {})
    by_id = {t["id"]: t for t in rep["tasks"]}
    assert by_id["bad"]["status"] == "failed",    by_id["bad"]["status"]
    assert by_id["dep"]["status"] == "skipped",   by_id["dep"]["status"]
    assert by_id["ind"]["status"] == "succeeded", by_id["ind"]["status"]
    print(f"  bad=failed, dep=skipped, ind=succeeded ✓")


def test_decisions_in_report(binary):
    spec = {
        "workflow": {
            "name": "decision-test",
            "tasks": [{"id": "decide", "skill": "s", "inputs": {}}],
        }
    }

    class DecisionDriver(EngineDriver):
        def _handle_skill(self, msg):
            self._write_raw({
                "type": "skill_result",
                "invocation_id": msg["invocation_id"],
                "output_json": '"done"',
                "error": None,
                "decisions": [
                    {"at_ms": 5,  "summary": "chose strategy A", "rationale": "lowest cost"},
                    {"at_ms": 10, "summary": "adjusted threshold", "rationale": "signal weak"},
                ],
            })

    rep = DecisionDriver(binary).run(spec, {})
    span = rep["tasks"][0]
    assert len(span.get("decisions", [])) == 2, f"expected 2 decisions: {span}"
    assert span["decisions"][0]["summary"] == "chose strategy A"
    print(f"  decisions={[d['summary'] for d in span['decisions']]} ✓")


def test_template_resolution(binary):
    """${input.x} and ${taskId.output} are resolved correctly by the engine."""
    spec = {
        "workflow": {
            "name": "template-test",
            "inputs": {"ticker": {"type": "string", "required": True}},
            "tasks": [
                {"id": "step1", "skill": "echo", "inputs": {"t": "${input.ticker}"}},
                {"id": "step2", "skill": "wrap",  "inputs": {"v": "${step1.output}"},
                 "depends_on": ["step1"]},
            ],
            "output": "${step2.output}",
        }
    }
    received = {}

    def skill_fn(skill, inputs):
        received[skill] = dict(inputs)
        if skill == "echo":
            assert inputs["t"] == "MSFT", f"template not resolved: {inputs}"
            return "price:300"
        if skill == "wrap":
            assert inputs["v"] == "price:300", f"output not passed: {inputs}"
            return f"wrapped:{inputs['v']}"
        raise ValueError(skill)

    rep = EngineDriver(binary, skill_fn=skill_fn).run(spec, {"ticker": "MSFT"})
    assert rep["status"] == "succeeded", rep
    assert rep.get("output") == "wrapped:price:300", f"output={rep.get('output')}"
    print(f"  template resolved, output={rep['output']} ✓")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    binary = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BIN)

    if not os.path.isfile(binary):
        print(f"ERROR: binary not found at {binary}")
        print("Build it:  cd engine && go build -o orchestrator ./cmd/orchestrator")
        sys.exit(1)

    tests = [
        ("basic run (market-analysis, 4 tasks)",        test_basic_run),
        ("parallelism (a∥b then join c)",               test_parallelism),
        ("fail-fast: failed task → downstream skipped", test_fail_fast),
        ("retry (retryable error, succeeds attempt 3)", test_retry),
        ("continue-on-error isolates branch",           test_continue_on_error),
        ("decisions surfaced in task spans",            test_decisions_in_report),
        ("template resolution (input + task output)",   test_template_resolution),
    ]

    print(f"\nGo engine binary: {binary}")
    print(f"Running {len(tests)} end-to-end tests\n")

    passed = 0
    for name, fn in tests:
        print(f"- {name}")
        try:
            fn(binary)
            passed += 1
        except Exception as exc:
            print(f"  FAILED: {exc}")
            import traceback; traceback.print_exc()

    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
