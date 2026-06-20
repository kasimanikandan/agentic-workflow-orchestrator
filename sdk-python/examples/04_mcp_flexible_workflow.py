"""
Workflow 4 — MCP-Orchestrated Analysis Pipeline
=================================================
Demonstrates flexible MCP integration: all three levels working together
in one workflow.

  Level 1 — Direct MCP tool calls (stateless)
  Level 2 — Pre-wrapped MCP skills (semantic, reusable)
  Level 3 — Managed MCP servers (cached, lifecycle-managed)

Users pick the right abstraction level for their needs.

    cd sdk-python && python3 examples/04_mcp_flexible_workflow.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator import Orchestrator, Registry, Workflow, MockLLM
from orchestrator.mcp_integration import ManagedMCPRegistry

# ------------------------------------------------------------------
# Mock MCP server handlers for offline demo
# ------------------------------------------------------------------

def mock_filesystem_handler(tool_name: str, args: dict):
    """Mock filesystem MCP server."""
    if tool_name == "list_files":
        path = args.get("path", ".")
        return {
            "path": path,
            "files": ["main.py", "utils.py", "config.py", "test.py"],
        }
    elif tool_name == "read_file":
        path = args.get("path", "file")
        return f"# File: {path}\n\ndef function():\n    pass\n\n# No type hints, sparse docstrings"
    raise ValueError(f"Unknown tool: {tool_name}")


def mock_web_handler(tool_name: str, args: dict):
    """Mock web MCP server."""
    if tool_name == "fetch":
        url = args.get("url", "url")
        return (
            "Python Best Practices:\n"
            "1. Use type hints for all functions\n"
            "2. Write comprehensive docstrings\n"
            "3. Follow PEP 8 naming conventions\n"
            "4. Use meaningful variable names\n"
            "5. Add unit tests for all public functions"
        )
    raise ValueError(f"Unknown tool: {tool_name}")


# ------------------------------------------------------------------
# Workflow spec: Three tasks using three different MCP levels
# ------------------------------------------------------------------

SPEC = {
    "workflow": {
        "name": "mcp-flexible-analysis",
        "inputs": {
            "project_dir": {"type": "string", "required": True}
        },
        "tasks": [
            # Task 1: Level 1 — Direct tool call (simplest)
            {
                "id": "scan_files_direct",
                "skill": "level1.direct_tool_call",
                "inputs": {"dir": "${input.project_dir}"}
            },
            # Task 2: Level 2 — Pre-wrapped skill (semantic)
            {
                "id": "read_main",
                "skill": "level2.fs_read",
                "depends_on": ["scan_files_direct"],
                "inputs": {"path": "${input.project_dir}/main.py"}
            },
            # Task 3: Level 2 — Another wrapped skill
            {
                "id": "fetch_best_practices",
                "skill": "level2.web_fetch",
                "inputs": {"url": "https://docs.python.org/best-practices"}
            },
            # Task 4: Level 3 — Managed server with caching
            {
                "id": "comprehensive_analysis",
                "skill": "level3.managed_analysis",
                "depends_on": ["read_main", "fetch_best_practices"],
                "inputs": {
                    "main_content": "${read_main.output.content}",
                    "best_practices": "${fetch_best_practices.output.content}",
                    "project_dir": "${input.project_dir}"
                }
            }
        ],
        "output": "${comprehensive_analysis.output}"
    }
}

# ------------------------------------------------------------------
# MCP Registry Setup
# ------------------------------------------------------------------

mcp_registry = ManagedMCPRegistry()
mcp_registry.register(
    "filesystem",
    tools=["list_files", "read_file"],
    handler=mock_filesystem_handler
)
mcp_registry.register(
    "web",
    tools=["fetch"],
    handler=mock_web_handler
)

# ------------------------------------------------------------------
# Register Skills (using all three MCP levels)
# ------------------------------------------------------------------

reg = Registry()


# ===== LEVEL 1: Direct MCP tool calls =====
@reg.skill("level1.direct_tool_call")
def level1_direct_tool_call(ctx, inputs):
    """Level 1: Direct stateless MCP tool call.

    Use case: One-off tool call, don't need semantic wrapping.
    """
    directory = inputs["dir"]

    # Spawn server, call tool, return result (no caching)
    server = mcp_registry.get_or_spawn("filesystem")
    result = server.call_tool("list_files", {"path": directory})

    ctx.record_decision(
        f"Level 1: Scanned {directory}, found {len(result['files'])} files",
        rationale="Direct MCP tool call — no semantic wrapper"
    )
    return {"files": result["files"], "level": 1}


# ===== LEVEL 2: Pre-wrapped MCP skills =====
@reg.skill("level2.fs_read")
def level2_fs_read(ctx, inputs):
    """Level 2: Pre-wrapped filesystem skill.

    Use case: Frequently used operation, want clean semantic interface.
    """
    path = inputs["path"]

    # Managed server (cached if already in use)
    server = mcp_registry.get_or_spawn("filesystem")
    content = server.call_tool("read_file", {"path": path})

    ctx.record_decision(
        f"Level 2: Read {path}",
        rationale="Pre-wrapped fs.read_file skill"
    )
    return {"content": content, "path": path, "level": 2}


@reg.skill("level2.web_fetch")
def level2_web_fetch(ctx, inputs):
    """Level 2: Pre-wrapped web skill."""
    url = inputs["url"]

    server = mcp_registry.get_or_spawn("web")
    content = server.call_tool("fetch", {"url": url})

    ctx.record_decision(
        f"Level 2: Fetched {url}",
        rationale="Pre-wrapped web.fetch skill"
    )
    return {"content": content, "url": url, "level": 2}


# ===== LEVEL 3: Managed MCP servers with LLM analysis =====
@reg.skill("level3.managed_analysis")
def level3_managed_analysis(ctx, inputs):
    """Level 3: Complex analysis using managed servers + LLM.

    Use case: Multiple MCP calls, need connection pooling and lifecycle
    management. Cached servers are reused from earlier tasks.
    """
    main_content = inputs["main_content"]
    best_practices = inputs["best_practices"]
    project_dir = inputs["project_dir"]

    # Get/reuse managed server (filesystem already running from level2)
    fs_server = mcp_registry.get_or_spawn("filesystem")

    # Make multiple calls to same server (connection is cached)
    file_list = fs_server.call_tool("list_files", {"path": project_dir})
    config_content = fs_server.call_tool("read_file", {"path": f"{project_dir}/config.py"})

    # Now analyze with LLM
    analysis = ctx.llm(
        messages=[{
            "role": "user",
            "content": (
                f"Code review of a Python project:\n\n"
                f"Main file:\n{main_content}\n\n"
                f"Config file:\n{config_content}\n\n"
                f"Best practices:\n{best_practices}\n\n"
                f"Provide assessment in JSON format with:\n"
                f"{{\n"
                f'  "score": 0-100,\n'
                f'  "strengths": [...],\n'
                f'  "improvements": [...],\n'
                f'  "critical": [...]\n'
                f"}}"
            )
        }],
        model="claude-opus-4-8"
    )

    try:
        result = json.loads(analysis.text)
    except json.JSONDecodeError:
        # MockLLM might return a simple string, not JSON
        result = {
            "score": 85,
            "strengths": ["clear structure", "good naming"],
            "improvements": ["add type hints", "expand docstrings"],
            "critical": []
        }

    score = result.get("score", 85)
    ctx.record_decision(
        f"Level 3: Comprehensive analysis complete, score={score}",
        rationale="Managed MCP servers + LLM analysis pipeline",
        data={
            "files_analyzed": len(file_list["files"]),
            "improvements_found": len(result.get("improvements", [])),
            "llm_tokens": analysis.tokens_in + analysis.tokens_out
        }
    )
    return {
        "score": score,
        "strengths": result.get("strengths", []),
        "improvements": result.get("improvements", []),
        "critical": result.get("critical", []),
        "level": 3
    }


# ------------------------------------------------------------------
# Run
# ------------------------------------------------------------------

if __name__ == "__main__":
    wf = Workflow.from_dict(SPEC)
    orch = Orchestrator(reg, llm=MockLLM())

    print("=== MCP Flexible Integration Demo ===")
    print("(All three MCP levels working together)\n")

    try:
        report = orch.run_sync(wf, inputs={"project_dir": "/my/project"})

        print("=== Execution Summary ===\n")
        for task in report.tasks:
            print(f"[{task.id}]")
            print(f"  Status: {task.status}  Duration: {task.duration_ms}ms")
            if task.decisions:
                for d in task.decisions:
                    print(f"  └─ {d.summary}")
                    if d.data:
                        print(f"     data: {json.dumps(d.data)}")
            print()

        print(f"Status: {report.status}")
        if report.errors:
            print(f"Errors: {report.errors}")

        if report.output:
            print("\n=== Output ===")
            out = report.output
            print(f"Score: {out['score']}/100")
            print(f"Strengths: {', '.join(out['strengths'][:2])}")
            print(f"Improvements: {', '.join(out['improvements'][:2])}")
            if out['critical']:
                print(f"Critical issues: {', '.join(out['critical'][:2])}")
        else:
            print("No output (task failed)")

        if report.status == "succeeded":
            print(f"\n✓ All three MCP levels executed successfully")
            print(f"  Level 1 (direct):   scan_files_direct")
            print(f"  Level 2 (wrapped):  read_main, fetch_best_practices")
            print(f"  Level 3 (managed):  comprehensive_analysis")
            print(f"\n  Managed server 'filesystem' reused across Level 2 and Level 3 tasks")
            print(f"  Total duration: {report.duration_ms}ms")
            print(f"  Critical path: {' → '.join(report.critical_path)}")
        else:
            for t in report.tasks:
                if t.status == "failed":
                    print(f"\nTask {t.id} failed: {t.error}")

    finally:
        # Cleanup all managed MCP servers
        mcp_registry.cleanup()
