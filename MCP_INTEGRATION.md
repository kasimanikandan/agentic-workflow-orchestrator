# MCP Integration Guide

The Orchestrator supports **flexible MCP (Model Context Protocol) server integration** at three abstraction levels, giving users the freedom to choose what fits their needs.

## Quick Start

```python
from orchestrator import Orchestrator, Registry, Workflow
from orchestrator.mcp_integration import ManagedMCPRegistry

# Register MCP server
mcp_reg = ManagedMCPRegistry()
mcp_reg.register("filesystem", tools=["list_files", "read_file"])

# Use it in skills
@reg.skill("analyze")
def analyze(ctx, inputs):
    server = mcp_reg.get_or_spawn("filesystem")
    files = server.call_tool("list_files", {"path": "."})
    return {"files": files}

# Run (servers auto-cleanup)
orch = Orchestrator(reg)
report = orch.run_sync(wf, inputs={})
mcp_reg.cleanup()
```

---

## The Three Levels

### Level 1: Direct Tool Calls (Stateless)

**API:**
```python
@reg.tool("mcp.filesystem.list")
def mcp_fs_list(path: str):
    # Spawn server on demand, call tool, return result
    pass

@reg.skill("task")
def task(ctx, inputs):
    files = ctx.call_tool("mcp.filesystem.list", path=".")
    return files
```

**Characteristics:**
- Simplest, most direct
- No server wrapper, no lifecycle management
- Server spawned per call (no caching)
- Stateless: each call is independent

**Use case:** One-off tool calls where you don't need semantic wrapping.

**Example:**
```python
# Just need to list files once, don't care about caching
content = ctx.call_tool("mcp.fs.list", path="/tmp")
```

---

### Level 2: Pre-wrapped MCP Skills (Semantic)

**API:**
```python
from orchestrator.mcp_integration import mcp_skill

@mcp_skill("filesystem", "read_file", mcp_registry=mcp_reg)
def fs_read(ctx, inputs):
    # ctx._mcp_result contains the tool result
    result = ctx._mcp_result
    return {"content": result, "path": inputs["path"]}

@reg.skill("fs_read")  # Pre-registered name
def fs_read_wrapper(ctx, inputs):
    # Wrapper handles MCP details automatically
    pass
```

**Characteristics:**
- Semantic wrapper around MCP tools
- Feels like a normal skill to the caller
- Hides MCP implementation details
- Reusable across workflows

**Use case:** Frequently used operations where you want a clean semantic interface.

**Example:**
```python
@mcp_skill("filesystem", "read_file")
def read_code_file(ctx, inputs):
    # Caller just sees a normal skill
    # MCP details are hidden
    return {"content": ctx._mcp_result}

@reg.skill("analyze_code")
def analyze(ctx, inputs):
    code = ctx.call_skill("read_code_file", {"path": "main.py"})
    # Analyze code...
```

---

### Level 3: Managed MCP Servers (Advanced)

**API:**
```python
from orchestrator.mcp_integration import ManagedMCPRegistry

mcp_reg = ManagedMCPRegistry()
mcp_reg.register("filesystem", tools=["list_files", "read_file", "write_file"])
mcp_reg.register("web", tools=["fetch", "search"])

@reg.skill("complex_analysis")
def analyze(ctx, inputs):
    # First call: server spawned and cached
    fs_server = mcp_reg.get_or_spawn("filesystem")
    
    files = fs_server.call_tool("list_files", {"path": "."})
    content = fs_server.call_tool("read_file", {"path": "main.py"})
    
    # Second skill uses same server (connection reused)
    return {"files": files, "content": content}
```

**Characteristics:**
- Server spawned on first `get_or_spawn()` call
- Cached for subsequent tasks (connection pooling)
- Multiple calls to same server reuse connection
- Full lifecycle management (spawn, connect, cleanup)
- Perfect for complex multi-call analysis tasks

**Use case:** Complex workflows where you make multiple calls to the same MCP server and want to reuse the connection.

**Example:**
```python
# Task 1: Fetch files
@reg.skill("list_files")
def list_files(ctx, inputs):
    fs = mcp_reg.get_or_spawn("filesystem")
    return fs.call_tool("list_files", {"path": inputs["dir"]})

# Task 2: Read multiple files (reuses cached filesystem server)
@reg.skill("read_files")
def read_files(ctx, inputs):
    fs = mcp_reg.get_or_spawn("filesystem")  # Returns cached instance
    for file in inputs["files"]:
        content = fs.call_tool("read_file", {"path": file})
        # ... process ...
```

---

## Mixing Levels in One Workflow

You can use all three levels in the same workflow:

```python
SPEC = {
    "workflow": {
        "name": "mixed-mcp",
        "tasks": [
            # Level 1: Direct tool call
            {"id": "t1", "skill": "level1.direct"},
            
            # Level 2: Pre-wrapped skill
            {"id": "t2", "skill": "fs.read", "depends_on": ["t1"]},
            
            # Level 3: Managed server
            {"id": "t3", "skill": "level3.complex", "depends_on": ["t2"]},
        ]
    }
}
```

---

## API Reference

### ManagedMCPRegistry

```python
class ManagedMCPRegistry:
    def register(self, name: str, tools: List[str], 
                 command: Optional[List[str]] = None,
                 handler: Optional[Callable] = None)
        """Register an MCP server spec."""
    
    def get_or_spawn(self, server_name: str) -> MCPServer
        """Get cached server, or spawn it if needed."""
    
    def get(self, server_name: str) -> Optional[MCPServer]
        """Get a cached server without spawning."""
    
    def cleanup(self)
        """Shut down all running servers."""
    
    def list_servers(self) -> List[str]
        """List all registered server names."""
    
    def list_tools(self, server_name: str) -> List[str]
        """List all tools for a server."""
```

### MCPServer

```python
class MCPServer:
    def connect(self)
        """Establish connection to MCP server."""
    
    def disconnect(self)
        """Shut down server and clean up."""
    
    def call_tool(self, tool_name: str, args: Dict) -> Any
        """Call a tool on this server."""
```

### Decorators

```python
@mcp_skill(server_name: str, tool_name: str, 
           mcp_registry: Optional[ManagedMCPRegistry] = None)
def skill_handler(ctx, inputs):
    """Decorator to create a pre-wrapped MCP skill."""
    # ctx._mcp_result contains the tool result
```

---

## Rate Limiting

MCP server calls are metered against the per-provider rate bucket:

```python
{
    "workflow": {
        "providers": {
            "filesystem": {"rate_limit": {"requests": 100, "per": "1m"}},
            "web": {"rate_limit": {"requests": 20, "per": "1m"}}
        },
        "tasks": [
            {"id": "t1", "skill": "fs.read", "provider": "filesystem"},
            {"id": "t2", "skill": "web.fetch", "provider": "web"}
        ]
    }
}
```

Each MCP server can have its own rate limit. The orchestrator enforces limits globally.

---

## Lifecycle & Cleanup

Level 3 servers must be cleaned up after the run:

```python
try:
    report = orch.run_sync(wf, inputs={})
finally:
    mcp_reg.cleanup()  # Shut down all servers
```

**Or use a context manager pattern:**
```python
class MCPOrchestrator(Orchestrator):
    def __init__(self, registry, mcp_registry, **kwargs):
        self.mcp_registry = mcp_registry
        super().__init__(registry, **kwargs)
    
    def run_sync(self, wf, inputs):
        try:
            return super().run_sync(wf, inputs)
        finally:
            self.mcp_registry.cleanup()
```

---

## Testing & Mocking

For testing, register mock handlers instead of real servers:

```python
def mock_filesystem_handler(tool_name: str, args: dict):
    if tool_name == "list_files":
        return ["file1.py", "file2.py"]
    elif tool_name == "read_file":
        return f"# Content of {args['path']}"
    raise ValueError(f"Unknown tool: {tool_name}")

mcp_reg = ManagedMCPRegistry()
mcp_reg.register("filesystem", 
                 tools=["list_files", "read_file"],
                 handler=mock_filesystem_handler)
```

The registry will call your handler instead of spawning a real server.

---

## Examples

| Example | What it shows |
|---|---|
| [examples/04_mcp_flexible_workflow.py](sdk-python/examples/04_mcp_flexible_workflow.py) | All three levels working together in one workflow |

---

## FAQ

**Q: When should I use Level 1 vs Level 2 vs Level 3?**

- **Level 1:** One-off tool call, don't need semantic wrapping
- **Level 2:** Frequently used operation, want clean semantic interface
- **Level 3:** Multiple calls to same server, need connection pooling + lifecycle

**Q: Can I mix levels in the same workflow?**

Yes! Use whichever level fits each task.

**Q: How are MCP servers cleaned up?**

Call `mcp_reg.cleanup()` at the end of your run, or use a context manager.

**Q: Do MCP calls respect rate limits?**

Yes. Each MCP server can have its own rate bucket configured in the workflow spec.

**Q: Can I use multiple MCP servers in one task?**

Yes. Get multiple servers and call their tools:
```python
@reg.skill("multi_server")
def multi(ctx, inputs):
    fs = mcp_reg.get_or_spawn("filesystem")
    web = mcp_reg.get_or_spawn("web")
    
    files = fs.call_tool("list_files", {...})
    content = web.call_tool("fetch", {...})
```

**Q: What if an MCP server crashes?**

Level 3 servers are spawned once and cached. If a server crashes, the connection is lost. Future calls will fail. v1.1 will add automatic reconnect.

---

## Implementation Status

- ✅ Level 1 direct tool calls
- ✅ Level 2 pre-wrapped skills
- ✅ Level 3 managed servers with caching
- ✅ Rate limiting integration
- ✅ Mock support for testing
- 🔄 Automatic reconnect (v1.1)
- 🔄 Distributed MCP servers (v1.1)
