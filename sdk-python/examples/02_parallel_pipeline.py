"""
Workflow 2 — Parallel Data Pipeline
=====================================
Fetch from two independent sources at the same time, then merge.
Introduces: parallel tasks, join step, tools, retry policy, timing proof.

    cd sdk-python && python3 examples/02_parallel_pipeline.py
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator import Orchestrator, Registry, Workflow

SPEC = {
    "workflow": {
        "name": "news-aggregator",
        "concurrency": {"max_parallel": 4},
        "inputs": {
            "topic": {"type": "string", "required": True}
        },
        "tasks": [
            # These two tasks share no dependency — they run in PARALLEL
            {
                "id": "fetch_tech",
                "skill": "feed.fetch",
                "inputs": {"source": "techcrunch", "topic": "${input.topic}"},
                "retry": {"max": 2, "backoff": "exponential", "base": "100ms"}
            },
            {
                "id": "fetch_finance",
                "skill": "feed.fetch",
                "inputs": {"source": "bloomberg", "topic": "${input.topic}"},
                "retry": {"max": 2, "backoff": "exponential", "base": "100ms"}
            },
            # This task waits for BOTH — a join
            {
                "id": "merge",
                "skill": "feed.merge",
                "depends_on": ["fetch_tech", "fetch_finance"],
                "inputs": {
                    "tech":    "${fetch_tech.output}",
                    "finance": "${fetch_finance.output}",
                    "topic":   "${input.topic}"
                }
            }
        ],
        "output": "${merge.output}"
    }
}

# ------------------------------------------------------------------
# Tools — registered once, callable from any skill via ctx.call_tool
# ------------------------------------------------------------------
reg = Registry()

@reg.tool("http.get")
def http_get(url: str):
    time.sleep(0.15)        # simulate 150ms network latency
    return {"url": url, "status": 200}

# ------------------------------------------------------------------
# Skills
# ------------------------------------------------------------------
@reg.skill("feed.fetch")
def feed_fetch(ctx, inputs):
    source = inputs["source"]
    topic  = inputs["topic"]

    # Calls the registered tool — engine meters it against the provider bucket
    resp = ctx.call_tool("http.get", url=f"https://{source}.com/api?q={topic}")

    # Simulated articles
    articles = [
        {"title": f"[{source}] {topic} moves markets",   "source": source},
        {"title": f"[{source}] Analysts weigh in on {topic}", "source": source},
    ]
    ctx.record_decision(
        f"fetched {len(articles)} articles from {source}",
        rationale=f"HTTP {resp['status']} — primary endpoint healthy"
    )
    return {"source": source, "articles": articles, "count": len(articles)}

@reg.skill("feed.merge")
def feed_merge(ctx, inputs):
    tech    = inputs["tech"]
    finance = inputs["finance"]
    all_articles = tech["articles"] + finance["articles"]

    ctx.record_decision(
        f"merged {tech['count']} + {finance['count']} = {len(all_articles)} articles",
        rationale="deduplication not needed — sources are disjoint"
    )
    return {
        "topic":   inputs["topic"],
        "total":   len(all_articles),
        "sources": [tech["source"], finance["source"]],
        "articles": all_articles
    }

# ------------------------------------------------------------------
# Run
# ------------------------------------------------------------------
if __name__ == "__main__":
    wf = Workflow.from_dict(SPEC)

    t0     = time.monotonic()
    report = Orchestrator(reg).run_sync(wf, inputs={"topic": "AI"})
    wall   = (time.monotonic() - t0) * 1000

    print("=== Report ===")
    for task in report.tasks:
        print(f"  {task.id:15s}  status={task.status}  duration={task.duration_ms}ms")
        for d in task.decisions:
            print(f"                  decision: {d.summary}")

    out = report.output
    print(f"\nOutput  : topic={out['topic']}, total={out['total']} articles, "
          f"sources={out['sources']}")
    print(f"Status  : {report.status}  (wall={wall:.0f}ms — "
          f"fetch_tech∥fetch_finance ran in parallel, not sequentially)")
    print(f"Critical path: {' → '.join(report.critical_path)}")

    # Prove parallelism: two 150ms fetches should finish in ~150ms, not 300ms
    assert wall < 280, f"Expected parallel execution (~150ms), got {wall:.0f}ms"
    print("\n✓ Parallelism confirmed: two 150ms fetches completed in one pass")
