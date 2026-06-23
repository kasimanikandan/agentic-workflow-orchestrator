# Changelog

All notable changes to the Orchestrator SDK will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-06-23

### Major Changes
- **Go Engine is Default:** Orchestrator now uses Go engine by default (`engine="go"`)
- **Python SDK is Wrapper:** Refactored to be a thin wrapper around Go orchestrator
- **NDJSON Protocol:** Implemented communication between Python SDK and Go engine via stdin/stdout
- **Workflow Serialization:** Added `Workflow.to_dict()` method
- **Report Deserialization:** Added `Report.from_dict()` method
- **Engine Path Function:** Added `get_engine_path()` to locate Go binary

### Added
- `engine` parameter to Orchestrator (default="go", fallback="python")
- `engine_path` parameter for custom Go binaries
- `get_engine_path()` function to auto-detect bundled Go binary
- Subprocess communication via NDJSON protocol
- Lazy engine path resolution

### Changed
- Default execution mode is now Go engine (production-ready)
- Python engine available as fallback for development/debugging
- **100% backward compatible** with v1.0.0 API

### Documentation
- Added `PYTHON_SDK_ARCHITECTURE.md` - Complete architecture guide
- Added `PYTHON_SDK_IS_GO_WRAPPER.md` - Verification document
- Updated `SDK_AND_ENGINE.md` - Reflects Go as default
- Updated all documentation to reflect v1.1.0

### Performance
- Go engine: true parallelism (1000+ tasks/sec, no GIL)
- Python engine: fallback for development (10-50 tasks/sec)

## [1.0.0] - 2026-06-23

### Added
- **7 LLM Providers:** Anthropic Claude, OpenAI GPT, Google Gemini, xAI Grok, Hugging Face, Azure OpenAI, MockLLM
- Multi-provider LLM support with per-task selection
- Token usage tracking for cost attribution
- Example demonstrating multi-provider usage
- Complete LLM provider documentation

### Features (from 0.1.0, expanded)
- Core orchestration: DAG scheduler, worker pool, rate limiting, resilience
- Skill and tool registration system
- 7 LLM providers with pluggable interface
- MCP support with three abstraction levels
- Workflow templating with variable resolution
- Retry policies and timeout enforcement
- Per-task and per-provider rate limiting
- Comprehensive execution reports
- Python SDK with async-ready API
- Go reference engine (both engines available)

### Documentation
- `DESIGN.md` - Architecture (13 sections)
- `QUICKSTART.md` - 3 runnable examples
- `SDK_AND_ENGINE.md` - Python SDK + Go engine relationship
- `LLM_INTEGRATION.md` - Complete provider guide
- `LLM_NOT_FOR_ORCHESTRATION.md` - LLM usage clarification
- `LLM_PROVIDERS_SUMMARY.md` - Provider comparison
- `MCP_INTEGRATION.md` - MCP 3-level guide
- `PACKAGE_SUMMARY.md` - Complete inventory
- `TESTING.md` - Test scenarios

### Examples
- 6 runnable examples (hello_world, parallel, llm, mcp, multi-provider, market)

### Status
- Published to PyPI: https://pypi.org/project/agentic-workflow-orchestrator/

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
