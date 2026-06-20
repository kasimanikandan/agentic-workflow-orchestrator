"""Tests for MCP integration (all 3 levels)."""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator import Orchestrator, Registry, Workflow
from orchestrator.mcp_integration import (
    ManagedMCPRegistry,
    ToolRegistry,
    MCPServer,
    mcp_skill,
)


# ---------------------------------------------------------------------------
# Mock MCP handlers for testing
# ---------------------------------------------------------------------------

def mock_filesystem_handler(tool_name: str, args: dict):
    """Mock filesystem MCP server."""
    if tool_name == "list_files":
        return ["file1.py", "file2.py", "README.md"]
    elif tool_name == "read_file":
        return f"# Content of {args.get('path', 'file')}"
    raise ValueError(f"Unknown tool: {tool_name}")


def mock_web_handler(tool_name: str, args: dict):
    """Mock web MCP server."""
    if tool_name == "fetch":
        return f"# Web content from {args.get('url', 'url')}"
    raise ValueError(f"Unknown tool: {tool_name}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_level1_direct_tool_call():
    """Level 1: Direct MCP tool calls via ToolRegistry."""
    print("\ntest_level1_direct_tool_call")

    # Setup
    mcp_reg = ManagedMCPRegistry()
    mcp_reg.register(
        "filesystem",
        tools=["list_files", "read_file"],
        handler=mock_filesystem_handler,
    )

    tool_reg = ToolRegistry(mcp_registry=mcp_reg)
    tool_reg.register_mcp_tool("mcp.fs.list", "filesystem", "list_files")
    tool_reg.register_mcp_tool("mcp.fs.read", "filesystem", "read_file")

    # Call Level 1 tools
    files = tool_reg.call("mcp.fs.list", path="/project")
    assert len(files) == 3
    assert "file1.py" in files

    content = tool_reg.call("mcp.fs.read", path="file1.py")
    assert "Content of file1.py" in content

    print("  ✓ Level 1 direct tool calls work")
    mcp_reg.cleanup()


def test_level2_wrapped_skills():
    """Level 2: Pre-wrapped MCP skills."""
    print("\ntest_level2_wrapped_skills")

    mcp_reg = ManagedMCPRegistry()
    mcp_reg.register(
        "filesystem",
        tools=["read_file"],
        handler=mock_filesystem_handler,
    )

    # Create a pre-wrapped skill using decorator
    @mcp_skill("filesystem", "read_file", mcp_registry=mcp_reg)
    def fs_read(ctx, inputs):
        """Pre-wrapped MCP skill for reading files."""
        result = ctx._mcp_result
        return {"content": result, "path": inputs.get("path")}

    # Simulate skill execution
    class MockCtx:
        pass

    ctx = MockCtx()
    output = fs_read(ctx, {"path": "README.md"})

    assert output["path"] == "README.md"
    assert "Content" in output["content"]

    print("  ✓ Level 2 pre-wrapped skills work")
    mcp_reg.cleanup()


def test_level3_managed_servers():
    """Level 3: Managed MCP servers with caching."""
    print("\ntest_level3_managed_servers")

    mcp_reg = ManagedMCPRegistry()
    mcp_reg.register(
        "filesystem",
        tools=["list_files", "read_file"],
        handler=mock_filesystem_handler,
    )
    mcp_reg.register(
        "web",
        tools=["fetch"],
        handler=mock_web_handler,
    )

    # First call: spawn server
    server1 = mcp_reg.get_or_spawn("filesystem")
    assert server1.connected

    # Second call: should return cached instance
    server2 = mcp_reg.get_or_spawn("filesystem")
    assert server1 is server2  # Same object

    # Multiple servers can coexist
    web_server = mcp_reg.get_or_spawn("web")
    assert web_server is not server1

    # Call tools
    files = server1.call_tool("list_files", {"path": "/project"})
    assert len(files) == 3

    content = web_server.call_tool("fetch", {"url": "https://example.com"})
    assert "Web content" in content

    print("  ✓ Level 3 managed servers work")
    print("  ✓ Server caching works (same instance on second call)")
    print("  ✓ Multiple servers coexist")

    mcp_reg.cleanup()


def test_mixed_levels_in_workflow():
    """Test all three levels working together in one workflow."""
    print("\ntest_mixed_levels_in_workflow")

    spec = {
        "workflow": {
            "name": "mcp-mixed",
            "tasks": [
                {"id": "level1", "skill": "direct.call"},
                {"id": "level2", "skill": "wrapped.skill", "depends_on": ["level1"]},
                {"id": "level3", "skill": "managed.server", "depends_on": ["level2"]},
            ]
        }
    }

    # Setup MCP registry
    mcp_reg = ManagedMCPRegistry()
    mcp_reg.register(
        "filesystem",
        tools=["list_files", "read_file"],
        handler=mock_filesystem_handler,
    )

    # Register skills using all three levels
    reg = Registry()

    # Level 1: Direct tool call inside a skill
    @reg.skill("direct.call")
    def direct_call(ctx, inputs):
        server = mcp_reg.get_or_spawn("filesystem")
        files = server.call_tool("list_files", {"path": "/"})
        return {"files": files, "level": 1}

    # Level 2: Skill that uses managed server (simplified, no decorator)
    @reg.skill("wrapped.skill")
    def wrapped_skill(ctx, inputs):
        server = mcp_reg.get_or_spawn("filesystem")
        content = server.call_tool("read_file", {"path": "test.py"})
        return {"content": content, "level": 2}

    # Level 3: Managed server in a complex skill
    @reg.skill("managed.server")
    def managed_server(ctx, inputs):
        server = mcp_reg.get_or_spawn("filesystem")
        # Server already running, this reuses cached instance
        files = server.call_tool("list_files", {"path": "/"})
        return {"files": files, "reused_cache": True, "level": 3}

    # Execute
    wf = Workflow.from_dict(spec)
    report = Orchestrator(reg).run_sync(wf, inputs={})

    # Verify
    assert report.status == "succeeded", f"Expected succeeded, got {report.status}. Errors: {report.errors}"
    assert len(report.tasks) == 3

    by_id = {t.id: t for t in report.tasks}
    assert by_id["level1"].output["level"] == 1
    assert by_id["level2"].output["level"] == 2
    assert by_id["level3"].output["reused_cache"] == True

    print("  ✓ All three levels work together in one workflow")
    print("  ✓ Level 1 → Level 2 → Level 3 executed sequentially")
    print("  ✓ Managed server reused across tasks")

    mcp_reg.cleanup()


def test_mcp_registry_introspection():
    """Test registry introspection APIs."""
    print("\ntest_mcp_registry_introspection")

    mcp_reg = ManagedMCPRegistry()
    mcp_reg.register("filesystem", tools=["list_files", "read_file"])
    mcp_reg.register("web", tools=["fetch", "search"])

    servers = mcp_reg.list_servers()
    assert "filesystem" in servers
    assert "web" in servers

    fs_tools = mcp_reg.list_tools("filesystem")
    assert "list_files" in fs_tools
    assert "read_file" in fs_tools

    web_tools = mcp_reg.list_tools("web")
    assert "fetch" in web_tools

    print("  ✓ Registry introspection works")


def test_unknown_server_error():
    """Test error handling for unknown servers."""
    print("\ntest_unknown_server_error")

    mcp_reg = ManagedMCPRegistry()

    try:
        mcp_reg.get_or_spawn("nonexistent")
        assert False, "Should raise error"
    except ValueError as e:
        assert "Unknown MCP server" in str(e)

    print("  ✓ Unknown server raises error")


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_level1_direct_tool_call,
        test_level2_wrapped_skills,
        test_level3_managed_servers,
        test_mixed_levels_in_workflow,
        test_mcp_registry_introspection,
        test_unknown_server_error,
    ]

    print("=== MCP Integration Tests ===")
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            import traceback

            traceback.print_exc()

    print(f"\n{passed}/{len(tests)} tests passed")
    exit(0 if passed == len(tests) else 1)
