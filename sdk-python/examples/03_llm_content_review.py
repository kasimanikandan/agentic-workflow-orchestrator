"""
Workflow 3 — LLM Content Review Pipeline
==========================================
Fetch a piece of content, moderate it with an LLM, then route
(approve / flag / reject) based on the moderation result.

Introduces: LLM-backed skill, ctx.llm(), ctx.record_decision(),
            per-provider rate limit, MockLLM for offline dev,
            AnthropicProvider for production.

    cd sdk-python && python3 examples/03_llm_content_review.py

To run against real Claude (needs ANTHROPIC_API_KEY):
    ANTHROPIC_API_KEY=sk-... python3 examples/03_llm_content_review.py --real
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator import Orchestrator, Registry, Workflow, MockLLM, AnthropicProvider

SPEC = {
    "workflow": {
        "name": "content-review",
        "concurrency": {"max_parallel": 4},
        "providers": {
            # Separate rate bucket for LLM calls — won't starve other tasks
            "anthropic": {"rate_limit": {"requests": 50, "per": "1m"}}
        },
        "defaults": {
            "retry":    {"max": 2, "backoff": "exponential", "base": "500ms"},
            "timeout":  "30s",
            "on_error": "fail_fast"
        },
        "inputs": {
            "content_id": {"type": "string", "required": True}
        },
        "tasks": [
            {
                "id": "fetch_content",
                "skill": "content.fetch",
                "inputs": {"id": "${input.content_id}"}
            },
            {
                # LLM-backed skill — classifies the text
                "id": "moderate",
                "skill": "llm.moderate",
                "provider": "anthropic",
                "depends_on": ["fetch_content"],
                "inputs": {"text": "${fetch_content.output.text}"}
            },
            {
                # Routes based on the moderation score — pure logic, no LLM
                "id": "route",
                "skill": "content.route",
                "depends_on": ["moderate"],
                "inputs": {
                    "content_id": "${input.content_id}",
                    "verdict":    "${moderate.output}"
                }
            }
        ],
        "output": "${route.output}"
    }
}

# ------------------------------------------------------------------
# Skills
# ------------------------------------------------------------------
reg = Registry()

CONTENT_DB = {
    # MockLLM labels "net-negative" if text contains: cut, miss, down, loss, negative, fall
    "post-001": {"text": "Great tutorial on building REST APIs with Python and FastAPI.",
                 "author": "alice"},   # net-positive  → approved
    "post-002": {"text": "The docs fall short of expectations but the library is usable.",
                 "author": "bob"},     # net-negative  → flagged for review
    "post-003": {"text": "Total loss of funds. Negative returns. Critical security miss.",
                 "author": "carol"},   # net-negative  → rejected (multiple risk words)
}

@reg.skill("content.fetch")
def content_fetch(ctx, inputs):
    content_id = inputs["id"]
    doc = CONTENT_DB.get(content_id)
    if not doc:
        raise ValueError(f"content not found: {content_id}")
    ctx.record_decision(f"fetched content {content_id!r}",
                        rationale=f"author={doc['author']}")
    return doc

@reg.skill("llm.moderate")
def llm_moderate(ctx, inputs):
    text = inputs["text"]

    result = ctx.llm(
        messages=[{
            "role": "user",
            "content": (
                f"Moderate this content and respond with JSON only.\n\n"
                f"Content: {text}\n\n"
                f'Respond: {{"label":"safe|borderline|harmful","score":0.0-1.0,"reason":"..."}}'
            )
        }],
        model="claude-opus-4-8",
    )

    raw = json.loads(result.text)

    # Map MockLLM's binary output to the safe/borderline/harmful taxonomy.
    # Real Claude returns these labels directly; this mapping only applies offline.
    if raw.get("label") == "net-positive":
        verdict = {"label": "safe",       "score": 0.1, "reason": "no risk signals detected"}
    else:
        # Use risk-word density in the source text to distinguish borderline vs harmful.
        risk_words = ("loss", "negative", "miss", "critical", "security", "cut", "fall")
        hits = sum(1 for w in risk_words if w in text.lower())
        if hits >= 2:
            verdict = {"label": "harmful",    "score": 0.9, "reason": f"{hits} risk signals found"}
        else:
            verdict = {"label": "borderline", "score": 0.6, "reason": "some risk signals present"}

    ctx.record_decision(
        f"moderation verdict: {verdict['label']} (score={verdict['score']})",
        rationale=verdict["reason"],
        data={"tokens_used": result.tokens_in + result.tokens_out}
    )
    return verdict

@reg.skill("content.route")
def content_route(ctx, inputs):
    cid     = inputs["content_id"]
    verdict = inputs["verdict"]
    label   = verdict["label"]
    score   = verdict["score"]

    if label == "safe" or score < 0.3:
        action = "approved"
    elif label == "borderline" or score < 0.7:
        action = "flagged_for_review"
    else:
        action = "rejected"

    ctx.record_decision(
        f"routed {cid!r} → {action}",
        rationale=f"label={label}, score={score}"
    )
    return {"content_id": cid, "action": action, "verdict": verdict}

# ------------------------------------------------------------------
# Run
# ------------------------------------------------------------------
def run_for(content_id: str, llm):
    wf     = Workflow.from_dict(SPEC)
    report = Orchestrator(reg, llm=llm).run_sync(wf, inputs={"content_id": content_id})

    out = report.output
    print(f"\n  content_id : {out['content_id']}")
    print(f"  action     : {out['action']}")
    print(f"  verdict    : label={out['verdict']['label']}, score={out['verdict']['score']}")
    for task in report.tasks:
        for d in task.decisions:
            print(f"  [{task.id}] {d.summary}")
    if report.totals.llm_tokens_in:
        print(f"  llm tokens : in={report.totals.llm_tokens_in} "
              f"out={report.totals.llm_tokens_out}")
    return report

if __name__ == "__main__":
    use_real_llm = "--real" in sys.argv

    if use_real_llm:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            sys.exit("Set ANTHROPIC_API_KEY to use real Claude")
        llm = AnthropicProvider(model="claude-opus-4-8", api_key=api_key)
        print("Using real Claude (Anthropic)\n")
    else:
        llm = MockLLM()
        print("Using MockLLM (offline — pass --real to use Claude)\n")

    print("=== Content Review Pipeline ===")
    for cid in ["post-001", "post-002", "post-003"]:
        print(f"\n--- {cid} ---")
        run_for(cid, llm)
