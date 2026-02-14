# mcpp

A lightweight MCP server that loads multiple tools from a single process. Instead of running a separate MCP server for every tool, mcpp acts as a multiplexer: one stdio server, many tool modules, zero coordination overhead.

## Why

The [Model Context Protocol](https://modelcontextprotocol.io/) gives AI agents (Claude Code, Codex, etc.) a standard way to call external tools. But the default pattern is **one server per tool** -- each with its own process, its own startup cost, and its own configuration entry. That gets unwieldy fast.

mcpp inverts this. You register tool modules in a single `tools.yaml` file. Each module is a directory with a `tool.yaml` manifest and a `mcpptool.py` implementation. The server discovers them at startup, serves all their schemas through one `tools/list`, and routes `tools/call` requests to the right module. Adding a new tool means creating a directory and restarting the server. No changes to the server code. No new MCP config entries.

## Features

- **One server, many tools** -- single process, single config entry, unlimited tool modules
- **Declarative contracts** -- each tool defines its schema in `tool.yaml` (JSON Schema), completely separate from implementation
- **Lazy loading** -- Python code is only imported on first call, not at startup. A broken module won't prevent the server from starting
- **External tools** -- modules can live anywhere on disk; just point to them in `tools.yaml`
- **Dual-audience responses** -- tools can return both human-readable display text and structured data for the agent, using MCP content annotations
- **Multi-user, multi-project** -- the [`mcpp-plan`](https://github.com/pacmac/mcpp-plan) tool tracks tasks per user per project from a single shared database
- **Timeout enforcement** -- per-call timeout via `SIGALRM` prevents runaway tools from blocking the server
- **Built-in help** -- agents can query `help` to discover available tools and their runtime configuration without importing any tool code
- **Human CLI** -- `cli.py` provides a command-line interface for testing and direct use

## Quick Start

### 1. Install

Clone the repo and ensure Python 3.10+ is available. The only external dependency is `pyyaml`.

```bash
git clone https://github.com/pacmac/mcpp.git
cd mcpp
pip install pyyaml
```

To include the [plan](https://github.com/pacmac/mcpp-plan) task manager (optional):

```bash
git clone https://github.com/pacmac/mcpp-plan.git ../mcpp-plan
```

Then add it to `tools.yaml`:
```yaml
modules:
  - path: ../mcpp-plan
```

### 2. Configure Your Agent

**Claude Code:**

```bash
claude mcp add mcpp --scope user \
  -- python3 /path/to/mcpp/mcpp.py
```

**Codex CLI** (`~/.codex/config.toml`):

```toml
[mcp_servers.mcpp]
command = "python3"
args = ["/path/to/mcpp/mcpp.py"]
env = { MCPP_LOG_LEVEL = "error", MCPP_TIMEOUT_SECONDS = "30" }
```

**Any MCP-compatible client** -- mcpp speaks JSON-RPC 2.0 over stdio:

```bash
python3 /path/to/mcpp/mcpp.py
```

### 3. Use It

Once configured, your agent sees all registered tools. In Claude Code they appear as `mcp__mcpp__<tool_name>`:

```
> What tools do you have from mcpp?

I have these tools available:
- fetch_page -- fetch and cache web content
- what_add -- scaffold a new plan directory
- plan_task_new -- create a new task with steps
- plan_task_list -- list all tasks
  ... (19 plan tools total)
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  AI Agent (Claude Code, Codex, etc.)                │
│                                                     │
│  tools/list  ──►  all tool schemas (from tool.yaml) │
│  tools/call  ──►  routed to correct module          │
└──────────────┬──────────────────────────────────────┘
               │ stdin/stdout (JSON-RPC 2.0)
┌──────────────▼──────────────────────────────────────┐
│  mcpp.py  (single process)                          │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │tools.yaml│  │ tool     │  │ routing  │          │
│  │ registry │─►│ discovery│─►│ table    │          │
│  └──────────┘  └──────────┘  └────┬─────┘          │
│                                   │                 │
│            ┌──────────┬───────────┼──────────┐      │
│            ▼          ▼           ▼          ▼      │
│       fetch_page    what       plan      your_tool  │
│       tool.yaml    tool.yaml   tool.yaml  tool.yaml │
│       mcpptool.py  mcpptool.py mcpptool.py  ...    │
└─────────────────────────────────────────────────────┘
```

**Startup:** Reads `tools.yaml` registry, parses each module's `tool.yaml` manifest. No Python imports yet.

**First call:** Lazily imports the module's `mcpptool.py`, caches it, routes the call.

**Subsequent calls:** Hits the cached module directly.

## How Tools Work

A tool module is a directory with two files:

```
tools/my_tool/
  tool.yaml       # declares the contract (schema)
  mcpptool.py     # implements the logic
```

### tool.yaml -- The Contract

This is the only file the server reads at startup. It defines what the tool does without any Python code.

```yaml
name: my_tool                    # unique module identifier
scope: local                     # "local" (workspace-relative) or "global"
about: "One-line description."   # shown in help listings

tools:
  - name: my_tool_search         # globally unique tool name
    description: "Search for items matching a query."
    inputSchema:
      type: object
      properties:
        query:
          type: string
          description: "Search query"
        limit:
          type: integer
          description: "Max results (default: 10)"
          minimum: 1
          maximum: 100
      required:
        - query
```

**Fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Module identifier. Must be unique across all registered modules |
| `scope` | No | `"local"` (default) -- tool operates on workspace files. `"global"` -- workspace-independent |
| `about` | No | One-line description shown by the `help` tool |
| `tools` | Yes | List of tool definitions, each with `name`, `description`, and `inputSchema` |

A single module can define multiple tools. The [`mcpp-plan`](https://github.com/pacmac/mcpp-plan) module defines 19 tools under one module name.

**Tool naming convention:** `<module>_<entity>_<action>`, e.g. `plan_task_new`, `plan_step_done`.

### mcpptool.py -- The Implementation

Must export an `execute()` function:

```python
def execute(tool_name: str, arguments: dict, context: dict | None = None) -> dict:
    """Handle a tool call.

    Args:
        tool_name:  Which tool was called (matches a name from tool.yaml)
        arguments:  Parameters from the agent, validated against inputSchema
        context:    Runtime info from the server:
                    {
                        "workspace_dir": "/abs/path/to/cwd",
                        "module_dir":    "/abs/path/to/this/module",
                        "module_scope":  "local"  # or "global"
                    }

    Returns:
        {"success": True, "result": <any>}                     # success
        {"success": True, "result": <data>, "display": "..."}  # success with display text
        {"success": False, "error": "description"}             # failure
    """
```

**That's the entire contract.** One function, three arguments, one dict return.

### Optional Exports

```python
def get_info(context: dict | None = None) -> dict:
    """Return runtime configuration for agent discoverability.
    Called by the built-in help tool."""
    return {
        "params": {
            "query": {"values": None, "default": None},
            "limit": {"values": None, "default": 10},
        }
    }

def initialize() -> dict:
    """Called once at module import time. Return {"success": False, ...} to warn."""
    return {"success": True}
```

### The Display Key

When a tool returns both `result` and `display`, the server emits two MCP content items with audience annotations:

```python
return {
    "success": True,
    "result": {"tasks": [...]},             # structured data for the agent
    "display": "**Tasks**\n- alpha\n- beta"  # markdown for the human
}
```

The agent receives the structured data for reasoning. The human sees the formatted markdown. This separation lets tools provide rich output to both audiences from a single call.

## The Registry (tools.yaml)

The top-level `tools.yaml` lists which modules to load:

```yaml
modules:
  - path: tools/fetch_page          # built-in, relative to tools.yaml
  - path: tools/what                # built-in
  - path: ../mcpp-plan              # external: github.com/pacmac/mcpp-plan
  - path: /opt/custom/my_tool       # absolute paths work too
```

Paths are resolved relative to the directory containing `tools.yaml`. Directories starting with `_` are ignored (used for templates).

**To add a tool:** create the directory, add an entry to `tools.yaml`, restart the server.

**To remove a tool:** delete its entry from `tools.yaml`, restart.

## Creating a New Tool

### From Template

```bash
cp -r tools/_template_pkg tools/my_tool
```

Edit `tools/my_tool/tool.yaml` to define your schema, edit `tools/my_tool/mcpptool.py` to implement your logic.

### From Scratch

**1. Create the directory:**

```bash
mkdir tools/my_tool
```

**2. Write tool.yaml:**

```yaml
name: my_tool
scope: local
about: "Does something useful."

tools:
  - name: my_tool_run
    description: "Run the tool with given parameters."
    inputSchema:
      type: object
      properties:
        target:
          type: string
      required:
        - target
```

**3. Write mcpptool.py:**

```python
from __future__ import annotations
from typing import Any

def execute(tool_name: str, arguments: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    if tool_name == "my_tool_run":
        target = arguments["target"]
        workspace = (context or {}).get("workspace_dir", ".")
        # ... do work ...
        return {"success": True, "result": {"target": target, "status": "done"}}

    return {"success": False, "error": f"Unknown tool: {tool_name}"}
```

**4. Register it:**

Add to `tools.yaml`:
```yaml
modules:
  - path: tools/my_tool
  # ... existing modules ...
```

**5. Restart the server.** The new tool appears in `tools/list` immediately.

## External Tools

Tool modules don't need to live inside the mcpp directory. Any directory on disk can be a tool module -- just point to it:

```yaml
modules:
  - path: /home/user/projects/my-tool    # absolute path
  - path: ../../other-repo/tool-module   # relative to tools.yaml
```

This is how the [`mcpp-plan`](https://github.com/pacmac/mcpp-plan) tool is integrated -- it lives in a separate repository and is referenced by path in the registry. The module has its own git history, tests, and release cycle. mcpp just loads it.

**Requirements for an external tool are identical:** a `tool.yaml` manifest and a `mcpptool.py` with `execute()`. No special packaging, no setup.py, no pip install.

## Multi-Module Tools

A single module can expose many tools. The [`mcpp-plan`](https://github.com/pacmac/mcpp-plan) module demonstrates this with 19 tools across four groups:

```yaml
name: plan
scope: local
about: "Manage project tasks and steps."

tools:
  # Task management (7 tools)
  - name: plan_task_new
  - name: plan_task_list
  - name: plan_task_show
  - name: plan_task_status
  - name: plan_task_switch
  - name: plan_task_archive
  - name: plan_task_notes

  # Step tracking (7 tools)
  - name: plan_step_list
  - name: plan_step_show
  - name: plan_step_switch
  - name: plan_step_done
  - name: plan_step_new
  - name: plan_step_delete
  - name: plan_step_notes

  # User identity (2 tools)
  - name: plan_user_show
  - name: plan_user_set

  # Project metadata (3 tools)
  - name: plan_project_show
  - name: plan_project_set
  - name: plan_readme
```

The `execute()` function routes internally:

```python
tool_map = {
    "plan_task_new": _cmd_task_new,
    "plan_task_list": _cmd_task_list,
    # ...
}

def execute(tool_name, arguments, context=None):
    handler = tool_map.get(tool_name)
    if not handler:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
    return handler(workspace_dir, arguments)
```

## Built-in Help

Every mcpp instance includes a `help` tool automatically. Agents can call it to discover what's available:

```python
# No arguments: list all modules
help()
# Returns: module names and their 'about' descriptions (no Python imports needed)

# With tool name: get runtime details
help(tool="fetch_page")
# Returns: output of that module's get_info(), including param defaults and valid values
```

## Multi-User, Multi-Project Support

The [`mcpp-plan`](https://github.com/pacmac/mcpp-plan) tool demonstrates mcpp's support for complex, stateful tools:

- **Single shared database** (`~/.config/plan/plan.db`) -- all projects, all users, one SQLite file
- **Automatic project detection** -- the workspace directory maps to a project; each project gets isolated task lists
- **Per-user state** -- each OS user has their own active task per project; `su` to another user sees their tasks
- **Cross-project isolation** -- running from `/project-a` shows project-a's tasks; running from `/project-b` shows project-b's. Same server, same database, different scopes

```
~/.config/plan/plan.db
├── project: webapp     (CWD: /home/user/webapp)
│   ├── user: alice     → active task: auth-refactor
│   └── user: bob       → active task: api-migration
├── project: cli-tool   (CWD: /home/user/cli-tool)
│   └── user: alice     → active task: add-flags
```

The `scope: local` setting in `tool.yaml` tells the server to pass `workspace_dir` in the context, which the tool uses to resolve the correct project.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCPP_BASE_DIR` | Directory containing `mcpp.py` | Where to find `tools.yaml` |
| `MCPP_LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error` |
| `MCPP_TIMEOUT_SECONDS` | `30` | Per-tool-call timeout in seconds |

### Claude Code

```bash
# Add with environment overrides
claude mcp add mcpp --scope user \
  --env MCPP_LOG_LEVEL=error \
  --env MCPP_TIMEOUT_SECONDS=60 \
  -- python3 /path/to/mcpp/mcpp.py
```

### Direct JSON config (any MCP client)

```json
{
  "mcpServers": {
    "mcpp": {
      "command": "python3",
      "args": ["/path/to/mcpp/mcpp.py"],
      "env": {
        "MCPP_LOG_LEVEL": "error"
      }
    }
  }
}
```

## Human CLI

For testing and direct use without an AI agent:

```bash
# List all registered tools
python3 cli.py list

# Call a tool
python3 cli.py call fetch_page --url https://example.com --max_chars 5000

# Get help on a specific tool
python3 cli.py call help --tool plan_task_new
```

## Project Layout

```
mcpp/
├── mcpp.py              # MCP server (reads stdin, writes stdout)
├── cli.py               # Human CLI wrapper
├── tools.yaml           # Module registry
├── tools/
│   ├── _template_pkg/   # Copy-paste starter for new tools
│   │   ├── tool.yaml
│   │   ├── mcpptool.py
│   │   └── helper.py
│   ├── fetch_page/      # URL fetcher with disk cache
│   │   ├── tool.yaml
│   │   └── mcpptool.py
│   └── what/            # Project scaffolding
│       ├── tool.yaml
│       └── mcpptool.py
└── README.md
```

## Protocol Compliance

mcpp implements the [Model Context Protocol](https://modelcontextprotocol.io/) over stdio with JSON-RPC 2.0:

| MCP Method | Supported | Notes |
|------------|-----------|-------|
| `initialize` | Yes | Returns protocol version `2025-06-18` |
| `tools/list` | Yes | Returns all tool schemas from all modules |
| `tools/call` | Yes | Routes to correct module, enforces timeout |
| `shutdown` | Yes | Sets shutdown flag |
| `notifications/*` | Yes | Silently acknowledged |
| Content annotations | Yes | `audience: ["user"]` / `["assistant"]` via display key |

## Inspired By

This project was inspired by [Andreas Spiess](https://www.youtube.com/@AndreasSpiess) and his [video on MCP server architecture](https://www.youtube.com/watch?v=5DG0-_lseR4).

## License

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/)

Free for personal use, research, education, non-profits, and government. Not permitted for commercial use. See [LICENSE](LICENSE) for the full text.
