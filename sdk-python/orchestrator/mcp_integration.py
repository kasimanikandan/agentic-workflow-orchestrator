"""
MCP (Model Context Protocol) integration for the Orchestrator.

Three levels of MCP support:
  Level 1: Direct tool calls (stateless, spawn-per-call)
  Level 2: Pre-wrapped MCP skills (semantic, reusable)
  Level 3: Managed MCP servers (cached, lifecycle-managed)
"""
import json
import subprocess
import threading
from typing import Any, Callable, Dict, List, Optional


class MCPTool:
    """Represents a single tool provided by an MCP server."""

    def __init__(self, name: str, description: str = "", schema: Optional[Dict] = None):
        self.name = name
        self.description = description
        self.schema = schema or {}

    def __repr__(self):
        return f"<MCPTool {self.name}>"


class MCPServer:
    """Represents an MCP server instance (e.g., "filesystem", "web")."""

    def __init__(self, name: str, tools: List[str], handler: Optional[Callable] = None):
        self.name = name
        self.tools = {t: MCPTool(t) for t in tools}
        self.handler = handler  # For mocking/testing
        self.process = None
        self.connected = False

    def connect(self):
        """Connect to the MCP server (spawn subprocess, establish stdio channel)."""
        self.connected = True

    def disconnect(self):
        """Disconnect and clean up."""
        if self.process:
            self.process.terminate()
        self.connected = False

    def call_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """Call a tool on this server."""
        if not self.connected:
            self.connect()

        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name} on {self.name}")

        # For demo/testing: use handler if provided
        if self.handler:
            return self.handler(tool_name, args)

        # In production: send JSON-RPC message over stdio/gRPC
        raise NotImplementedError(f"MCP server {self.name} not connected")

    def __repr__(self):
        return f"<MCPServer {self.name} tools={list(self.tools.keys())}>"


# ---------------------------------------------------------------------------
# Level 3: Managed MCP Server Registry
# ---------------------------------------------------------------------------

class ManagedMCPRegistry:
    """Manages MCP server lifecycle: spawn on demand, cache, cleanup."""

    def __init__(self):
        self.servers: Dict[str, MCPServer] = {}
        self.specs: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    def register(
        self,
        name: str,
        tools: List[str],
        command: Optional[List[str]] = None,
        handler: Optional[Callable] = None,
    ):
        """Register an MCP server spec.

        Args:
            name: "filesystem", "web", etc.
            tools: List of tool names provided by this server
            command: Command to spawn the server (e.g., ["mcp", "server", "filesystem"])
            handler: Mock handler for testing (takes tool_name, args → result)
        """
        self.specs[name] = {
            "tools": tools,
            "command": command,
            "handler": handler,
        }

    def get_or_spawn(self, server_name: str) -> MCPServer:
        """Get cached server, or spawn it if needed (Level 3 pattern)."""
        with self._lock:
            if server_name in self.servers:
                return self.servers[server_name]

            spec = self.specs.get(server_name)
            if not spec:
                raise ValueError(f"Unknown MCP server: {server_name}. Register it first.")

            print(f"  [MCP Level 3] Spawning managed server: {server_name}")
            server = MCPServer(
                server_name,
                spec["tools"],
                handler=spec["handler"]
            )
            server.connect()
            self.servers[server_name] = server
            return server

    def get(self, server_name: str) -> Optional[MCPServer]:
        """Get a cached server without spawning."""
        return self.servers.get(server_name)

    def cleanup(self):
        """Shut down all running servers."""
        with self._lock:
            for name, server in self.servers.items():
                print(f"  [MCP Level 3] Cleaning up: {name}")
                server.disconnect()
            self.servers.clear()

    def list_servers(self) -> List[str]:
        """List all registered server names."""
        return list(self.specs.keys())

    def list_tools(self, server_name: str) -> List[str]:
        """List all tools for a server."""
        if server_name not in self.specs:
            return []
        return self.specs[server_name]["tools"]


# ---------------------------------------------------------------------------
# Level 2: Pre-wrapped MCP Skills (decorator pattern)
# ---------------------------------------------------------------------------

def mcp_skill(server_name: str, tool_name: str, mcp_registry: Optional[ManagedMCPRegistry] = None):
    """Decorator to create a pre-wrapped MCP skill.

    Usage:
        @mcp_skill("filesystem", "read_file")
        def fs_read(ctx, inputs):
            # ctx.mcp_result contains the tool result
            # Implement skill logic here
            return {...}

    Args:
        server_name: Name of the MCP server ("filesystem", "web", etc.)
        tool_name: Name of the tool on that server
        mcp_registry: Optional ManagedMCPRegistry for Level 3 support
    """
    def decorator(fn: Callable) -> Callable:
        def wrapper(ctx, inputs):
            # Execute the MCP tool call (Level 2 pattern)
            print(f"    [MCP Level 2] Pre-wrapped skill {fn.__name__}")
            print(f"      Calling {server_name}.{tool_name}({inputs})")

            if mcp_registry:
                # Use managed server (Level 3 underneath)
                server = mcp_registry.get_or_spawn(server_name)
            else:
                # Spawn a temporary server (Level 1 underneath)
                server = MCPServer(server_name, [tool_name])
                server.connect()

            try:
                result = server.call_tool(tool_name, inputs)
                # Store result for the skill to use
                ctx._mcp_result = result
                # Call the wrapped skill function
                return fn(ctx, inputs)
            finally:
                if not mcp_registry:
                    server.disconnect()

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        wrapper._mcp_info = {"server": server_name, "tool": tool_name}
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Level 1: Direct Tool Calls (via Registry)
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Registry for tools that can be called via ctx.call_tool().

    Level 1 pattern: Tools are simple registered functions.
    No server wrapper, no lifecycle management.
    """

    def __init__(self, mcp_registry: Optional[ManagedMCPRegistry] = None):
        self.tools: Dict[str, Callable] = {}
        self.mcp_registry = mcp_registry

    def register_mcp_tool(
        self,
        namespace: str,
        server_name: str,
        tool_name: str,
    ) -> Callable:
        """Register an MCP tool as a callable tool.

        Usage:
            registry.register_mcp_tool("mcp.filesystem", "filesystem", "read_file")
            ctx.call_tool("mcp.filesystem.read_file", {"path": "..."})

        Args:
            namespace: Full tool name for calling (e.g., "mcp.filesystem.read_file")
            server_name: MCP server name
            tool_name: Tool name on that server
        """
        def mcp_tool_wrapper(**kwargs):
            print(f"    [MCP Level 1] Direct tool call: {namespace}")
            if self.mcp_registry:
                server = self.mcp_registry.get_or_spawn(server_name)
            else:
                server = MCPServer(server_name, [tool_name])
                server.connect()

            try:
                return server.call_tool(tool_name, kwargs)
            finally:
                if not self.mcp_registry:
                    server.disconnect()

        self.tools[namespace] = mcp_tool_wrapper
        return mcp_tool_wrapper

    def register_tool(self, name: str, fn: Callable):
        """Register a regular tool."""
        self.tools[name] = fn

    def call(self, name: str, **kwargs) -> Any:
        """Call a registered tool."""
        if name not in self.tools:
            raise ValueError(f"Unknown tool: {name}")
        return self.tools[name](**kwargs)

    def list_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(self.tools.keys())


# ---------------------------------------------------------------------------
# Orchestrator extension with MCP support
# ---------------------------------------------------------------------------

class MCPOrchestrator:
    """Mixin to add MCP support to Orchestrator."""

    def __init__(self, *args, mcp_registry: Optional[ManagedMCPRegistry] = None, **kwargs):
        self.mcp_registry = mcp_registry or ManagedMCPRegistry()
        super().__init__(*args, **kwargs)

    def run_sync_with_mcp(self, wf, inputs):
        """Run workflow with MCP server cleanup."""
        try:
            return self.run_sync(wf, inputs)
        finally:
            self.mcp_registry.cleanup()


__all__ = [
    "MCPServer",
    "MCPTool",
    "ManagedMCPRegistry",
    "ToolRegistry",
    "mcp_skill",
    "MCPOrchestrator",
]
