# LLM is NOT for Orchestration — A Critical Distinction

**TL;DR:** The orchestrator engine is 100% deterministic and never calls LLM. LLM is only available as a tool *within skills*.

---

## The Orchestrator (Deterministic, No LLM)

The orchestrator engine does **exactly** one thing: schedule and execute a DAG of tasks with:

- ✅ Dependency ordering (ensure task A completes before task B)
- ✅ Parallel execution (run independent tasks concurrently)
- ✅ Rate limiting (respect API quotas via token buckets)
- ✅ Retries (exponential backoff with jitter)
- ✅ Timeouts (cancel tasks that exceed deadline)
- ✅ Reporting (gather timing, errors, decisions)

It does **NOT** do:

- ❌ Call LLM to decide what tasks to run
- ❌ Use LLM to determine parallelism
- ❌ Use LLM to decide retry strategy
- ❌ Use LLM to route tasks
- ❌ Use LLM to classify errors

### Why Deterministic?

1. **Reproducibility:** Same input → same task execution order every time.
2. **Debugging:** Easy to replay, trace, and understand.
3. **Compliance:** Auditable decision-making (no AI non-determinism).
4. **Performance:** No LLM latency (API calls can be slow and fail).
5. **Cost:** Orchestration is free; LLM calls cost money.

---

## Skills (Deterministic or LLM-powered)

A **skill** is the implementation of one task. Skills are 100% in control of whether to call LLM.

```python
@registry.skill("process.content")
def process_content(ctx, inputs):
    # This skill decides what to do
    
    # Option 1: Deterministic logic (no LLM)
    if len(inputs["text"]) > 100:
        return {"category": "long", "action": "review"}
    
    # Option 2: Call LLM for reasoning (skill chooses this)
    result = ctx.llm(
        messages=[{"role": "user", "content": inputs["text"]}],
        model="claude-opus-4-8",
    )
    
    # Process LLM's response
    return {"category": result.text, "action": "approve"}
```

**The skill, not the orchestrator, decides whether to call LLM.**

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│ ORCHESTRATOR (deterministic, no LLM)                         │
│                                                              │
│  Input Workflow → DAG → Schedule Tasks → Track Failures     │
│                                                              │
│  All decisions:                                             │
│  - What task to run next (derived from DAG)               │
│  - When to retry (exponential backoff)                     │
│  - When to timeout (wall-clock deadline)                  │
│  → All deterministic, all fast, no API calls              │
└──────────────────────────────────────────────────────────────┘
                         ↓
┌──────────────────────────────────────────────────────────────┐
│ SKILL: task.example (user code, may use LLM)               │
│                                                              │
│  @registry.skill("task.example")                            │
│  def handler(ctx, inputs):                                  │
│      # Skill decision: do I need LLM?                       │
│      if inputs["needs_reasoning"]:                          │
│          result = ctx.llm(...)  ← OPTIONAL LLM CALL        │
│      else:                                                   │
│          result = deterministic_logic()  ← NO LLM          │
│      return result                                          │
└──────────────────────────────────────────────────────────────┘
```

---

## Key Examples

### Example 1: Content Moderation

```python
@registry.skill("content.moderate")
def moderate(ctx, inputs):
    """Moderate user-submitted content."""
    
    text = inputs["text"]
    
    # Step 1: Deterministic pre-filter (orchestrator doesn't do this)
    if len(text) > 10000:
        return {"action": "reject", "reason": "too_long"}
    
    # Step 2: THIS SKILL decides to call LLM
    # The ORCHESTRATOR did NOT tell it to do this
    result = ctx.llm(
        messages=[{"role": "user", "content": f"Is this safe? {text}"}],
        model="claude-opus-4-8",
    )
    
    # Step 3: Parse LLM response and decide
    if "unsafe" in result.text.lower():
        return {"action": "flag_for_review"}
    else:
        return {"action": "approve"}
```

**What the orchestrator does:**
- ✅ Ensures `content.moderate` runs after earlier tasks (if dependencies exist)
- ✅ Runs it in a worker thread
- ✅ Retries if it fails
- ✅ Tracks how long it took

**What the orchestrator does NOT do:**
- ❌ Decide to call LLM
- ❌ Route based on LLM output
- ❌ Adjust retries based on LLM response

---

### Example 2: Multi-Step Reasoning

```python
@registry.skill("market.analyze")
def analyze_market(ctx, inputs):
    """Analyze market using multiple LLM calls."""
    
    ticker = inputs["ticker"]
    
    # Call 1: Get sentiment (might use different model)
    sentiment_result = ctx.llm(
        messages=[{"role": "user", "content": f"News about {ticker}"}],
        model="claude-haiku-4-5",  # Cheaper model
    )
    
    # Call 2: Get recommendation (use better model)
    recommendation = ctx.llm(
        messages=[
            {"role": "user", "content": f"Based on {sentiment_result.text}, what to do?"}
        ],
        model="claude-opus-4-8",  # Better reasoning
    )
    
    # Orchestrator just sees this as: a task that happened to take N seconds
    # The orchestrator does NOT know about the two LLM calls inside
    return {"recommendation": recommendation.text}
```

**What the orchestrator sees:**
- ✅ Input: `{"ticker": "AAPL"}`
- ✅ Output: `{"recommendation": "buy"}`
- ✅ Tokens used: 150 in, 45 out (tracked)
- ✅ Duration: 2.3 seconds

**What the orchestrator does NOT care about:**
- ❌ How the skill made the decision
- ❌ That two LLM calls happened
- ❌ Which models were used (it just tracks totals)

---

### Example 3: What the Orchestrator DOES NOT Do

```python
@registry.skill("workflow.dispatch")
def dispatch(ctx, inputs):
    """WRONG: Trying to use LLM to decide what to do."""
    
    # ❌ This is wrong — the orchestrator already decided
    # which task to run (this skill). The skill shouldn't
    # call LLM to second-guess that.
    
    result = ctx.llm(
        messages=[{"role": "user", "content": "Should I run? Answer yes/no"}],
    )
    
    if "yes" in result.text.lower():
        return {"decision": "proceed"}
    else:
        return {"decision": "skip"}  # But orchestrator already scheduled this!
```

**Why this is wrong:**
- The orchestrator already determined this task should run.
- Calling LLM to re-decide wastes money and introduces non-determinism.
- If you want conditional logic, implement it in the skill or the workflow spec.

**Right way:**
```python
@registry.skill("workflow.dispatch")
def dispatch(ctx, inputs):
    """Right: Deterministic logic or one optional LLM call for reasoning."""
    
    if inputs["priority"] == "high":
        return {"decision": "proceed"}
    
    # Only use LLM if it adds value for your business logic
    result = ctx.llm(
        messages=[{"role": "user", "content": f"Classify: {inputs['item']}"}],
    )
    
    return {"decision": "proceed", "reasoning": result.text}
```

---

## Token & Cost Tracking

All LLM calls within skills are automatically tracked:

```python
report = orch.run_sync(workflow, {})

# Per-task LLM usage
for task in report.tasks:
    if task.llm_usage:
        cost = (task.llm_usage.tokens_in * 0.003 +
                task.llm_usage.tokens_out * 0.01) / 1000  # Example pricing
        print(f"{task.name}: ${cost:.3f}")

# Workflow-level summary
total_cost = (report.totals.llm_tokens_in * 0.003 +
              report.totals.llm_tokens_out * 0.01) / 1000
print(f"Total LLM cost: ${total_cost:.2f}")
```

---

## Testing & Determinism

Because the orchestrator is deterministic, tests are easy:

```python
def test_workflow():
    """Test without any API calls or LLM."""
    
    # Use MockLLM (deterministic, offline)
    registry = Registry()
    registry.skill("task1")(lambda ctx, inputs: {"result": "done"})
    
    # Workflow runs to completion, always the same
    orch = Orchestrator(registry, llm=MockLLM())
    report = orch.run_sync(workflow, {})
    
    # Assertions are stable
    assert report.totals.succeeded == 3
    assert report.totals.failed == 0
```

If the orchestrator used LLM, tests would be flaky and expensive.

---

## Decision Recording

Skills can record **why** they made a decision:

```python
@registry.skill("content.classify")
def classify(ctx, inputs):
    result = ctx.llm(messages=[...])
    
    # Record why this skill did what it did
    ctx.record_decision(
        action="approved",
        rationale=f"LLM classified as {result.text}",
        data={"llm_model": result.model, "confidence": 0.92},
    )
    
    return {"status": "approved"}
```

These decisions appear in the report for auditing:

```python
for decision in report.decisions:
    print(f"{decision.summary}: {decision.rationale}")
    # Output: approved: LLM classified as safe_content
```

---

## Summary Table

| Aspect | Orchestrator | Skills |
|---|---|---|
| **Determinism** | 100% | Depends on implementation |
| **Latency** | Fast (ms) | Variable (could call LLM) |
| **API calls** | None | Optional (skill chooses) |
| **Cost** | Free | Only if skill uses LLM |
| **Debugging** | Easy (no randomness) | Depends on LLM usage |
| **Reproducibility** | Yes (same input → same schedule) | Depends on LLM usage |
| **Responsibility** | Schedule tasks | Implement logic |

---

## Recap

1. **Orchestration is deterministic and never calls LLM.**
   - DAG walk, task scheduling, rate limiting, retries — all algorithmic.

2. **Skills control whether to call LLM.**
   - A skill is free to call LLM for reasoning.
   - Or a skill can use deterministic logic.
   - The skill author decides.

3. **LLM calls within skills are tracked.**
   - Tokens in/out recorded per task.
   - Can aggregate for cost attribution.

4. **The orchestrator doesn't know or care if LLM was used.**
   - It just sees: task ran, returned output, took N seconds.

5. **Use MockLLM for testing.**
   - Deterministic, offline, no API keys.
   - Identical interface to real providers.

---

**This design ensures the orchestration layer remains fast, reliable, and auditable, while skills have full freedom to use LLM when it makes sense for their business logic.**

🚀 Build deterministic, scalable workflows with optional intelligent skills!
