# MCP Stdio On-Demand Agent Wrapper - Scope

This document captures the high-level goals and boundaries of the project. Detailed protocol/module requirements live in `SPEC.md`, and practical usage/examples live in `IMPLEMENT.md`.

## 1. Core Principle

A single, immutable **MCP (Model Context Protocol) stdio wrapper** that acts as a local, on-demand server for CLI agents. The wrapper handles all MCP protocol I/O (stdin/stdout) and routes tool calls to dynamically discovered, pluggable Python modules. Once built, the wrapper never changes, all functionality is added via new modules dropped into a designated directory.

This enables:
- **Write-once infrastructure**: Build the wrapper once, never modify it
- **Zero-friction extensibility**: Add tools by adding `.py` files
- **Modular architecture**: Each tool/feature is an independent module
- **Agent-agnostic**: Works with any CLI agent that supports MCP stdio protocol

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ CLI Agent (e.g., Claude Code, custom agent, etc.)              │
│                                                                 │
│ Sends: MCP requests via stdio (JSON-RPC)                       │
│ Receives: MCP responses via stdio (JSON-RPC)                   │
└────────────────────┬────────────────────────────────────────────┘
                     │ stdin/stdout
                     │
┌────────────────────▼────────────────────────────────────────────┐
│              MCP Stdio Wrapper (Immutable)                      │
│                                                                 │
│ • Reads JSON-RPC from stdin                                    │
│ • Parses MCP protocol messages                                 │
│ • Maintains tool registry (auto-populated)                     │
│ • Routes tool calls to correct module                          │
│ • Handles errors/responses                                     │
│ • Writes JSON-RPC to stdout                                    │
└────────────────────┬────────────────────────────────────────────┘
                     │
         ┌───────────┴────────────┐
         │                        │
    ┌────▼─────┐           ┌─────▼────┐
    │  Module  │           │  Module  │  ...
    │ Router   │           │ Manager  │
    └────┬─────┘           └─────┬────┘
         │                       │
         └───────────┬───────────┘
                     │
         ┌───────────▼──────────────┐
         │    Module Directory      │
         │  (Auto-discovered)       │
         │                          │
         │  ├── weather.py          │
         │  ├── calculator.py       │
         │  ├── file_ops.py         │
         │  └── custom_tool.py      │
         │                          │
         └──────────────────────────┘
```

### 2.1 Human CLI Interface (Optional)

For direct human usage without an agent, a CLI wrapper (`cli.py`) provides command-line access:

```
┌─────────────────────────────────────────────────────────────────┐
│ Human User                                                      │
│                                                                 │
│ Command: mymcp call fetch_page --url https://example.com       │
└────────────────────┬────────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────────┐
│              CLI Wrapper (cli.py)                               │
│                                                                 │
│ • Parse command-line arguments                                 │
│ • Spawn wrapper.py subprocess                                  │
│ • Send JSON-RPC messages (initialize, tools/list, tools/call)  │
│ • Parse responses                                              │
│ • Pretty-print output for humans                               │
└────────────────────┬────────────────────────────────────────────┘
                     │ stdin/stdout (same as agent)
┌────────────────────▼────────────────────────────────────────────┐
│              MCP Stdio Wrapper (wrapper.py)                     │
│                                                                 │
│                     [same as above]                            │
└─────────────────────────────────────────────────────────────────┘
```

**Key differences from agent usage:**
- **Input**: CLI arguments (`--arg value`) instead of JSON-RPC
- **Output**: Human-readable text instead of JSON
- **Lifecycle**: One-shot execution (spawn, call, exit) instead of persistent session
- **Workspace**: Uses shell's `$PWD` as `workspace_dir`

**Use cases:**
- Manual testing of tools
- Shell scripts and automation
- Quick ad-hoc tool invocation
- Headless environments without agent access

## 3. Wrapper Responsibilities

The wrapper is a **stateless, protocol-translating daemon** that:

### 3.1 Initialization
- **Startup**: On launch, scan the `modules/` directory
- **Module Discovery**: Import all `.py` files that are valid modules
- **Schema Extraction**: Extract `MODULE_NAME`, `TOOLS` schema from each module
- **Registry Building**: Aggregate all tools into a single MCP tools list
- **No Caching of Results**: Each call is independent (on-demand)

### 3.2 Protocol Handling
- **Read stdin**: Accept MCP JSON-RPC messages from the agent
- **Parse**: Deserialize JSON and validate against MCP spec
- **Handle Message Types**:
  - `initialize`: Return available tools (from registry)
  - `tools/list`: Return all tools from all modules
  - `tools/call`: Route to appropriate module and execute
  - `notifications/*`: Handle any MCP notifications
- **Error Handling**: Return proper MCP error responses for invalid requests
- **Write stdout**: Send JSON-RPC responses back to agent

### 3.3 Tool Routing
- **Match tool name** to source module based on registry
- **Call module's `execute(tool_name, arguments)` function**
- **Return result** wrapped in MCP response format
- **Timeout handling**: Implement reasonable timeout per tool call (configurable)

### 3.5 Local vs Global Modules (Forward Planning)

Some tools are workspace-scoped (local) and need the wrapper startup working directory as their datastore root. Other tools are module-scoped (global) and use a data source alongside the module code. Modules declare a `MODULE_SCOPE` slug (`local|global`) and receive wrapper-provided call context (e.g., `workspace_dir`) so they can resolve paths consistently.

Examples:
- `global`: a fetcher/service module that retrieves remote pages (does not depend on the caller workspace).
- `local`: a scaffolding/file-ops module that creates folders/files under the caller workspace.

### 3.4 Lifecycle
- **Stateless**: No persistent state between calls
- **Streaming**: Process requests as they arrive
- **Graceful shutdown**: Handle EOF on stdin, exit cleanly

## 4. Future Extensions (Not in Initial Release)

- **Module versioning**: Support multiple versions of same module
- **Conditional loading**: Load modules based on environment/config
- **Metrics collection**: Track tool call frequency, execution times
- **Hot reload**: Reload modules without restarting wrapper
- **Module dependencies**: Handle inter-module dependencies
- **Async support**: Non-blocking tool execution (if needed)

## 5. Deployment & Configuration (CRITICAL)

### 5.1 User-Scoped Configuration

**MOST IMPORTANT**: To configure this MCP server globally across all projects, use:

```bash
claude mcp add mymcp --scope user \
  --env MYMCP_LOG_LEVEL=error \
  --env MYMCP_TIMEOUT_SECONDS=30 \
  -- python3 /absolute/path/to/wrapper.py
```

### 5.2 Why --scope user Matters

**DO NOT manually edit config files.** After extensive investigation (2026-02-08), we discovered:

- ❌ **Manual editing fails**: Editing `~/.claude/settings.json` or `/root/.claude.json` leads to configuration hierarchy conflicts
- ❌ **Per-project config breaks**: Claude Code auto-creates project entries with empty `mcpServers: {}` that override global config
- ✅ **--scope user works**: The CLI command sets proper user scope that applies globally without conflicts

**Configuration Hierarchy Issues:**
1. Claude Code creates project entry when starting from ANY directory
2. New entries have `"mcpServers": {}` by default
3. Empty object overrides manually-configured global settings
4. Result: Tools work in some directories but not others
5. Solution: Use `--scope user` flag which properly configures user-level scope

**Key Takeaway:** The `claude mcp add --scope user` command is the ONLY reliable way to configure MCP servers globally. This is not documented well but is critical for multi-project workflows.

## 6. Success Criteria

The wrapper is complete when:

- ✅ Starts with zero configuration
- ✅ Auto-discovers all valid modules in `tools/` directory
- ✅ Aggregates all tool schemas into single registry
- ✅ Routes all MCP `tools/call` requests to correct module
- ✅ Handles all errors gracefully (never crashes, always responds)
- ✅ Can add new tools by dropping `.py` files (no wrapper changes)
- ✅ Works with any MCP-compliant CLI agent
- ✅ Passes all MCP protocol compliance checks
- ✅ Has comprehensive logging for debugging
