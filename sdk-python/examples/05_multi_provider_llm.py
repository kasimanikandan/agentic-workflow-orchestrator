#!/usr/bin/env python3
"""Multi-provider LLM example.

Demonstrates how to use different LLM providers (Claude, OpenAI, Gemini, etc.)
in skills, including cost optimization strategies.

Key concepts:
- Each skill can independently choose an LLM provider
- Use cheaper models for simple tasks, expensive models for complex reasoning
- LLM is used WITHIN skills, not by the orchestrator itself
- All LLM usage is tracked and reported
"""
import json
from orchestrator import (
    Orchestrator,
    Registry,
    Workflow,
    MockLLM,
    AnthropicProvider,
    OpenAIProvider,
    GeminiProvider,
)


def create_workflow() -> Workflow:
    """Create a workflow that demonstrates multi-provider LLM usage."""
    spec = {
        "name": "multi-provider-analysis",
        "tasks": [
            {
                "id": "analyze_sentiment",
                "skill": "nlp.sentiment",
                "description": "Analyze sentiment using Claude (best for reasoning)",
                "inputs": {"text": "${input.content}"},
                "outputs": ["sentiment", "confidence", "explanation"],
            },
            {
                "id": "classify_category",
                "skill": "nlp.classify",
                "description": "Classify text category using GPT-3.5 (faster, cheaper)",
                "inputs": {"text": "${input.content}"},
                "outputs": ["category", "score"],
            },
            {
                "id": "extract_entities",
                "skill": "nlp.entities",
                "description": "Extract entities using Gemini (multimodal-ready)",
                "inputs": {"text": "${input.content}"},
                "outputs": ["entities", "types"],
            },
            {
                "id": "summarize",
                "skill": "nlp.summarize",
                "description": "Summarize using Claude Haiku (cheap for summary)",
                "inputs": {
                    "sentiment": "${analyze_sentiment.output.sentiment}",
                    "category": "${classify_category.output.category}",
                    "entities": "${extract_entities.output.entities}",
                    "text": "${input.content}",
                },
                "outputs": ["summary"],
            },
        ],
    }
    return Workflow.from_dict(spec)


def register_skills(registry: Registry, use_mock: bool = True):
    """Register skills that use different LLM providers.

    Args:
        registry: Skill registry
        use_mock: If True, use MockLLM for all providers. Otherwise, use real providers.
    """

    @registry.skill("nlp.sentiment")
    def analyze_sentiment(ctx, inputs):
        """Analyze sentiment using Claude (best for reasoning)."""
        if use_mock:
            llm = MockLLM()
        else:
            # Use Claude Opus for complex reasoning
            llm = AnthropicProvider(model="claude-opus-4-8")

        result = llm.complete(
            messages=[
                {
                    "role": "user",
                    "content": f'Analyze sentiment: "{inputs["text"]}". Return JSON with "sentiment" (positive/negative/neutral), "confidence" (0-1), "explanation".',
                }
            ],
        )

        ctx.record_decision(
            "sentiment_analysis",
            rationale=f"Used {result.provider} ({result.model})",
            llm_tokens=result.tokens_in + result.tokens_out,
        )

        try:
            # Try to parse JSON response
            parsed = json.loads(result.text)
            return {
                "sentiment": parsed.get("sentiment", "unknown"),
                "confidence": parsed.get("confidence", 0.5),
                "explanation": parsed.get("explanation", result.text),
            }
        except json.JSONDecodeError:
            # Fallback if LLM didn't return valid JSON
            return {
                "sentiment": "unknown",
                "confidence": 0.0,
                "explanation": result.text,
            }

    @registry.skill("nlp.classify")
    def classify_category(ctx, inputs):
        """Classify category using GPT-3.5-turbo (faster, cheaper)."""
        if use_mock:
            llm = MockLLM()
        else:
            # Use OpenAI GPT-3.5 for faster, cheaper classification
            llm = OpenAIProvider(model="gpt-3.5-turbo")

        result = llm.complete(
            messages=[
                {
                    "role": "user",
                    "content": f'Classify this text into one category: news, product, feedback, or other. Text: "{inputs["text"]}"',
                }
            ],
        )

        ctx.record_decision(
            "classification",
            rationale=f"Used {result.provider} ({result.model}) for speed/cost",
            llm_tokens=result.tokens_in + result.tokens_out,
        )

        category = (
            result.text.lower().split()[0]
            if result.text
            else "unknown"
        )
        return {"category": category, "score": 0.85}

    @registry.skill("nlp.entities")
    def extract_entities(ctx, inputs):
        """Extract entities using Gemini (multimodal-ready)."""
        if use_mock:
            llm = MockLLM()
        else:
            # Use Gemini for multimodal capabilities and good performance
            llm = GeminiProvider(model="gemini-1.5-pro")

        result = llm.complete(
            messages=[
                {
                    "role": "user",
                    "content": f'Extract named entities (person, organization, location) from: "{inputs["text"]}"',
                }
            ],
        )

        ctx.record_decision(
            "entity_extraction",
            rationale=f"Used {result.provider} ({result.model})",
            llm_tokens=result.tokens_in + result.tokens_out,
        )

        return {
            "entities": [
                "Entity1",
                "Entity2",
            ],  # Simplified for demo
            "types": ["PERSON", "ORG"],
        }

    @registry.skill("nlp.summarize")
    def summarize(ctx, inputs):
        """Summarize using Claude Haiku (cheap for summary tasks)."""
        if use_mock:
            llm = MockLLM()
        else:
            # Use Claude Haiku for budget-friendly summarization
            llm = AnthropicProvider(model="claude-haiku-4-5")

        text = f"""
        Sentiment: {inputs['sentiment']}
        Category: {inputs['category']}
        Entities: {inputs['entities']}

        Original: {inputs['text']}
        """

        result = llm.complete(
            messages=[
                {
                    "role": "user",
                    "content": f'Summarize this analysis: {text}',
                }
            ],
        )

        ctx.record_decision(
            "summarization",
            rationale=f"Used {result.provider} ({result.model}) for cost efficiency",
            llm_tokens=result.tokens_in + result.tokens_out,
        )

        return {"summary": result.text}

    return registry


def main():
    """Run the multi-provider LLM workflow."""
    print("🤖 Multi-Provider LLM Workflow Example\n")
    print("This example demonstrates:")
    print("  - Using different LLM providers for different tasks")
    print("  - Cost optimization (cheap model for simple, expensive for complex)")
    print("  - LLM usage tracking and reporting\n")

    # Use MockLLM for deterministic demo (no API keys needed)
    use_real_llms = False

    if use_real_llms:
        print("⚠️  Using real LLM providers (requires API keys):")
        print("   ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY")
        print("   Set these environment variables before running.\n")
    else:
        print("✓ Using MockLLM for demo (deterministic, no API keys)\n")

    # Create workflow and register skills
    workflow = create_workflow()
    registry = Registry()
    register_skills(registry, use_mock=True)

    # Run with Python engine (in-process)
    print("Orchestrator: Starting workflow run...\n")
    orchestrator = Orchestrator(registry)

    report = orchestrator.run_sync(
        workflow,
        inputs={
            "content": "Claude just released a powerful new model that supports reasoning and tool use. It's amazing for multi-step tasks!"
        },
    )

    # Print results
    print("\n📋 TASK RESULTS:\n")
    for task_span in report.tasks:
        print(f"✓ {task_span.name}:")
        if task_span.output:
            for key, value in task_span.output.items():
                print(f"    {key}: {value}")
        if task_span.llm_usage:
            print(
                f"    LLM: {task_span.llm_usage.model} "
                f"({task_span.llm_usage.tokens_in}→{task_span.llm_usage.tokens_out} tokens)"
            )
        print()

    # Print LLM usage summary
    if report.totals.llm_tokens_in or report.totals.llm_tokens_out:
        print(f"📊 Total LLM Usage:")
        print(
            f"   Input tokens:  {report.totals.llm_tokens_in}"
        )
        print(
            f"   Output tokens: {report.totals.llm_tokens_out}"
        )
        print(
            f"   Total tokens:  {report.totals.llm_tokens_in + report.totals.llm_tokens_out}"
        )

    # Print execution summary
    print(f"\n✅ Workflow completed in {report.totals.duration_secs:.2f}s")
    print(f"   Successful tasks: {report.totals.succeeded}")
    print(f"   Failed tasks: {report.totals.failed}")

    # Show how to use real providers
    print("\n💡 To use real LLM providers:")
    print("   1. Install: pip install agentic-workflow-orchestrator[llm]")
    print("   2. Set API keys: ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.")
    print("   3. Change use_real_llms=True in main()")
    print("\n🚀 Each provider is swappable in individual skills!")


if __name__ == "__main__":
    main()
