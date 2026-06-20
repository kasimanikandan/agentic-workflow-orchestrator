# Changelog

All notable changes to the Orchestrator SDK will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-18

### Added
- Core orchestration engine: DAG scheduler, worker pool, rate limiting
- Skill and tool registration system
- LLM integration with Anthropic (Claude) support and MockLLM for testing
- MCP (Model Context Protocol) support with three levels of abstraction:
  - Level 1: Direct tool calls (stateless)
  - Level 2: Pre-wrapped MCP skills (semantic)
  - Level 3: Managed MCP servers (cached, lifecycle-managed)
- Workflow templating: `${input.x}`, `${taskId.output}` references
- Retry policies: exponential backoff, jitter support
- Per-task and per-provider rate limiting
- Comprehensive reporting: timing, LLM token usage, critical path, decisions
- Python SDK with async-ready API
- Go reference engine (gRPC + stdio transport)
- Full test suite (unit + integration + end-to-end)
- Four runnable examples (hello world, parallel pipeline, LLM review, MCP flexible)

### Documentation
- Design document (DESIGN.md)
- Quick start guide (QUICKSTART.md)
- Testing guide (TESTING.md)
- MCP integration reference (MCP_INTEGRATION.md)
- Full API reference in docstrings

## Roadmap

### v0.2.0 (planned)
- [ ] Dynamic fan-out (foreach loops spawning N parallel children)
- [ ] Sub-workflows (nested workflow execution)
- [ ] Durable state persistence (Redis/Postgres backend)
- [ ] Multi-tenant service mode with resumable runs
- [ ] Human-in-the-loop approval tasks
- [ ] Automatic reconnect for failed MCP servers

### v1.0.0 (planned)
- [ ] JavaScript/TypeScript SDK
- [ ] Java SDK
- [ ] Native Go client library
- [ ] Distributed workflow execution across multiple machines
- [ ] Advanced observability: distributed tracing, metrics export
- [ ] Workflow visualization dashboard
- [ ] Policy engine for compliance checks
