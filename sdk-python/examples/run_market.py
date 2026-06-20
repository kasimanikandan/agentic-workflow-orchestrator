"""Runnable example: the market-analysis workflow, fully offline (MockLLM).

    cd sdk-python && python3 examples/run_market.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator import MockLLM, Orchestrator, Registry, Workflow  # noqa: E402

reg = Registry()


# --- Tools (deterministic stand-ins for real APIs) ---
@reg.tool("http.get")
def http_get(url):
    time.sleep(0.05)  # simulate latency
    return {"url": url, "ok": True}


# --- Skills ---
@reg.skill("market.fetch")
def market_fetch(ctx, inputs):
    data = ctx.call_tool("http.get", url=f"/prices/{inputs['ticker']}")
    ctx.record_decision("selected primary feed", rationale="lowest latency", data={"feed": "primary"})
    return {"ticker": inputs["ticker"], "last": 199.4, "raw": data}


@reg.skill("news.fetch")
def news_fetch(ctx, inputs):
    ctx.call_tool("http.get", url=f"/news/{inputs['ticker']}")
    return "Company cuts full-year guidance; analysts flag a miss on margins."


@reg.skill("llm.classify")
def llm_classify(ctx, inputs):
    result = ctx.llm(
        messages=[{"role": "user", "content": f"Classify sentiment: {inputs['text']}"}],
        model="claude-opus-4-8",
    )
    parsed = json.loads(result.text)
    ctx.record_decision(
        f"classified news as {parsed['label']} (conf {parsed['confidence']})",
        rationale="headline cites guidance cut + margin miss",
    )
    return parsed


@reg.skill("analysis.summarize")
def analysis_summarize(ctx, inputs):
    prices = inputs["prices"]
    sentiment = inputs["sentiment"]
    return {
        "ticker": prices["ticker"],
        "last": prices["last"],
        "sentiment": sentiment["label"],
        "recommendation": "HOLD" if sentiment["label"] == "net-negative" else "BUY",
    }


def main():
    here = os.path.dirname(__file__)
    spec_path = os.path.join(here, "..", "..", "spec", "examples", "market-analysis.json")
    wf = Workflow.from_file(spec_path)

    orch = Orchestrator(reg, llm=MockLLM())
    report = orch.run_sync(wf, inputs={"ticker": "AAPL"})

    print(report.to_json())
    print("\n--- summary ---")
    print(f"status        : {report.status}")
    print(f"duration_ms   : {report.duration_ms}")
    print(f"critical_path : {' -> '.join(report.critical_path)}")
    print(f"output        : {report.output}")


if __name__ == "__main__":
    main()
