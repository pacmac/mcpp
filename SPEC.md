# MCP Stdio On-Demand Agent Wrapper - Specification

This document defines the protocol/module contracts and wrapper behavior. High-level project scope is in `SCOPE.md`, and practical usage/examples are in `IMPLEMENT.md`.

## 1. Module Structure and Contract

Every module is a Python file with a **mandatory interface**. The wrapper depends on this contract.

### 1.0 Module Scope (Local vs Global)

Modules may declare a scope slug:

```python
MODULE_SCOPE = "local"  # or "global"
```

- `local`: The module is workspace-scoped. Any persistent state is expected to live under the wrapper startup working directory (the "workspace directory").
- `global`: The module is module-scoped. Any persistent state is expected to live alongside the module code (the module directory).
- This is a forward-planning field. The wrapper may initially ignore it, but it must be available for future routing/policy decisions.

Examples:
- `global`: a "fetch_page" service module that retrieves remote content. Its bundled parsers/config live under `module_dir`, and any optional caches/logs are written under `module_dir` so behavior is independent of which workspace launched the wrapper.
- `local`: a "scaffold_project" module that creates folders/files. It treats the wrapper startup working directory (`workspace_dir`) as the root of all relative paths and writes inside that tree.

### 1.1 Module File Location
```
tools/
├── __init__.py          # Optional, empty file for package
├── weather.py           # Individual module
├── calculator.py
├── file_ops.py
├── llm_client.py
└── database.py
```

Two module layouts are supported:
- Directory modules only: `tools/<name>/main.py` (can include sibling `.py`/data files)

Files or directories starting with `_` are ignored.

### 1.2 Tool Naming Convention (MANDATORY)

All tool names MUST follow the pattern: `<module>_<item>_<action>`

**Rules:**
- Keep names SHORT (prefer abbreviations when clear)
- Use lowercase with underscores
- Module name is always the prefix
- Item identifies what the tool operates on
- Action describes what it does (may be omitted if obvious)

**Examples:**
- `fetch_page` - module=fetch, item=page, action implied (get)
- `spi_init` - module=spi, item=project implied, action=init
- `weather_forecast_get` - module=weather, item=forecast, action=get
- `db_record_create` - module=db, item=record, action=create
- `file_text_read` - module=file, item=text, action=read

**Exposure:** Tools are exposed via Claude Code as `mcp__mymcp__<toolname>`
- Example: `fetch_page` becomes `mcp__mymcp__fetch_page`
- The `mcp__mymcp__` prefix is added automatically by Claude Code

### 1.3 Module Required Exports

Every module MUST define:

#### `MODULE_NAME` (string)
```python
MODULE_NAME = "weather"
```
- **Unique identifier** for the module
- Used internally by router to identify which module owns a tool
- Must be alphanumeric (no spaces, special chars except `_`)
- If duplicate names exist, wrapper should error at startup

#### `TOOLS` (list of dict)
```python
TOOLS = [
    {
        "name": "get_weather",
        "description": "Fetch current weather for a location",
        "inputSchema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name or coordinates"
                },
                "units": {
                    "type": "string",
                    "enum": ["metric", "imperial"],
                    "description": "Temperature units"
                }
            },
            "required": ["location"]
        }
    },
    {
        "name": "get_forecast",
        "description": "Get weather forecast for next 7 days",
        "inputSchema": {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "days": {"type": "integer", "minimum": 1, "maximum": 7}
            },
            "required": ["location"]
        }
    }
]
```

- **List of tool definitions** this module provides
- Each tool is an MCP-compliant schema
- Schema must follow JSON Schema standard
- `inputSchema` describes expected arguments for that tool
- Tools are registered globally; names must be unique across all modules

#### `execute(tool_name: str, arguments: dict, context: dict | None = None) -> dict` (function)
```python
def execute(tool_name: str, arguments: dict, context: dict | None = None) -> dict:
    """
    Execute a tool call.

    Args:
        tool_name: Name of tool to execute (e.g., "get_weather")
        arguments: Dict of arguments matching the inputSchema
        context: Wrapper-provided call context (optional; may be None)

    Returns:
        dict with structure:
        {
            "success": bool,
            "result": <any>,  # Tool-specific result
            "error": str,     # Only if success=False
            "metadata": {}    # Optional, tool-specific metadata
        }
    """
    if tool_name == "get_weather":
        location = arguments.get("location")
        units = arguments.get("units", "metric")
        # Execute tool logic
        return {
            "success": True,
            "result": {
                "temperature": 72,
                "condition": "sunny",
                "location": location
            }
        }
    elif tool_name == "get_forecast":
        # Handle another tool
        return {"success": True, "result": [...]}
    else:
        return {
            "success": False,
            "error": f"Unknown tool: {tool_name}"
        }
```

##### Context Contract

The wrapper SHOULD pass a `context` dict to `execute()`. At minimum:

```python
{
    "workspace_dir": "/abs/path/to/wrapper-startup-cwd",
    "module_dir": "/abs/path/to/this-module-directory",
    "module_scope": "local"  # or "global"
}
```

Notes:
- `workspace_dir` must reflect the wrapper process working directory at startup (the directory the wrapper was launched from).
- The wrapper is designed to be **on-demand per workspace**: one wrapper process serves one workspace directory. If you need tool calls to operate on a different folder, launch a separate wrapper process from that folder (or otherwise set its startup working directory).
- `module_dir` is derived from the module's `__file__`.
- `module_scope` is the module's declared `MODULE_SCOPE` if present, otherwise wrapper-defined default (recommended default: `local`).
- Relative paths policy (recommended):
  - If `module_scope == "local"`: interpret relative file/folder paths as relative to `workspace_dir`.
  - If `module_scope == "global"`: interpret relative file paths as relative to `module_dir`.
- To preserve backward compatibility, the wrapper MAY support modules that only accept the 2-argument signature `execute(tool_name, arguments)` by detecting arity and calling accordingly.

### 1.4 Module Response Contract

The `execute()` function MUST always return a dict with:

```python
{
    "success": bool,           # Required: True if execution succeeded
    "result": <any>,           # Required if success=True; tool output
    "error": str,              # Required if success=False; error message
    "metadata": {}             # Optional: tool-specific metadata/diagnostics
}
```

**Success case:**
```python
{
    "success": True,
    "result": {"data": "..."},
    "metadata": {"execution_time_ms": 123}
}
```

**Failure case:**
```python
{
    "success": False,
    "error": "API rate limit exceeded",
    "metadata": {"retry_after_seconds": 60}
}
```

### 1.5 Module Constraints

- **Pure Python**: Standard library + pip-installed packages
- **No global state**: Each `execute()` call is independent
- **Exception handling**: Must catch all exceptions and return error dict (never raise)
- **Argument validation**: Trust that arguments match schema, but validate defensively
- **Timeouts**: Should not block indefinitely
- **Dependencies**: List in a `requirements.txt` at module level (optional but recommended)

### 1.6 Optional Module Features

Modules may optionally define:

#### `MODULE_DESCRIPTION` (string)
```python
MODULE_DESCRIPTION = "Provides weather data from OpenWeather API"
```
Human-readable description of module purpose.

#### `DEPENDENCIES` (list of string)
```python
DEPENDENCIES = ["requests>=2.28.0", "pydantic>=1.9.0"]
```
Python package requirements for this module.

#### `initialize()` function
```python
def initialize() -> dict:
    """
    Optional: Called once at wrapper startup.
    Useful for validating API keys, testing connections, etc.

    Returns:
        {
            "success": bool,
            "message": str
        }
    """
    # Validate API key exists
    if not os.getenv("OPENWEATHER_API_KEY"):
        return {"success": False, "message": "OPENWEATHER_API_KEY not set"}
    return {"success": True, "message": "Ready"}
```

Wrapper calls this during discovery; if returns False, logs warning but continues.

## 2. MCP Protocol Flow

### 2.1 Initialization Request
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {
            "name": "my-agent",
            "version": "1.0.0"
        }
    }
}
```

**Wrapper response:**
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "serverInfo": {
            "name": "mcp-tools-wrapper",
            "version": "1.0.0"
        }
    }
}
```

### 2.2 List Tools Request
```json
{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {}
}
```

**Wrapper response:**
```json
{
    "jsonrpc": "2.0",
    "id": 2,
    "result": {
        "tools": [
            {
                "name": "get_weather",
                "description": "Fetch current weather...",
                "inputSchema": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                }
            },
            {
                "name": "calculate",
                "description": "Perform calculation...",
                "inputSchema": {...}
            }
        ]
    }
}
```

### 2.3 Call Tool Request
```json
{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
        "name": "get_weather",
        "arguments": {
            "location": "San Francisco",
            "units": "metric"
        }
    }
}
```

**Wrapper response (success):**
```json
{
    "jsonrpc": "2.0",
    "id": 3,
    "result": {
        "content": [
            {
                "type": "text",
                "text": "{\"temperature\": 72, \"condition\": \"sunny\"}"
            }
        ]
    }
}
```

**Wrapper response (tool error):**
```json
{
    "jsonrpc": "2.0",
    "id": 3,
    "result": {
        "content": [
            {
                "type": "text",
                "text": "Error: Location not found"
            }
        ],
        "isError": true
    }
}
```

**Wrapper response (protocol error):**
```json
{
    "jsonrpc": "2.0",
    "id": 3,
    "error": {
        "code": -32601,
        "message": "Method not found"
    }
}
```

### 2.4 Shutdown / Exit (Client Lifecycle)

Some clients use a JSON-RPC lifecycle similar to LSP:

1. Client sends a `shutdown` request (expects a response with `result: null`).
2. Client sends an `exit` notification (no response); server exits.

The wrapper should tolerate this lifecycle. It may also simply exit cleanly on stdin EOF.

## 3. Module Discovery Process

### 3.1 At Startup
1. **Scan directory**: List all `.py` files in `tools/` directory
2. **Filter**: Skip `__init__.py`, files starting with `_`
3. **Import**: Dynamically import each module
4. **Validate**: Check for required exports (`MODULE_NAME`, `TOOLS`, `execute`)
5. **Register**: Build global tool registry (key = tool name, value = module name + execute function)
6. **Check collisions**: Error if tool names are duplicated across modules
7. **Log**: Print summary of loaded modules and tools
8. **Optional init**: Call each module's `initialize()` if present

### 3.2 Error Cases
- **Import error**: Log warning, skip module, continue
- **Missing `MODULE_NAME`**: Log error, skip module
- **Missing `execute()`**: Log error, skip module
- **Invalid `TOOLS` schema**: Log error, skip module
- **Duplicate tool name**: Log error, exit (fail-fast)
- **Initialize fails**: Log warning, module still available

## 4. Execution Flow for Tool Calls

1. **Wrapper receives stdin**: `{"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "xyz", "arguments": {...}}}`
2. **Parse & validate**: Check JSON-RPC structure, method name
3. **Lookup tool**: Search registry for tool name "xyz"
4. **Module not found**: Return error response
5. **Module found**: Get module + execute function
6. **Build context**: Include `workspace_dir` (wrapper startup cwd), `module_dir`, and `module_scope`
7. **Call execute**: `result = module.execute("xyz", arguments, context)` (or 2-arg form for legacy modules)
8. **Handle timeout**: If execution > timeout_seconds, return timeout error
9. **Handle exception**: If execute() raises, catch and return error
10. **Format response**: Wrap result in MCP response format
11. **Write stdout**: Send JSON-RPC response back to agent

## 5. Configuration & Extensibility

### 5.1 Wrapper Configuration
- **Module path**: Configurable (default `tools/`)
- **Timeout**: Default 30 seconds, configurable per-module or globally
- **Log level**: debug/info/warning/error
- **Auto-reload**: For development (reload modules on each call)
- **Strict mode**: Fail on any module error vs. continue with warnings

## 6. Logging & Debugging

### 6.1 Wrapper Logs
- **Startup**: "Loaded N modules with M tools"
- **Per module**: "Loaded module 'weather' with 2 tools"
- **Per call**: "[tools/call] tool=get_weather, execution_time=150ms"
- **Errors**: Full stack traces for debugging

### 6.2 Module Logs
Modules can use Python's `logging` module; wrapper passes through to stderr/file.

### 6.3 Debug Mode
```yaml
log_level: "debug"
```
Enables verbose logging of all MCP messages and execution details.

## 7. Performance Considerations

- **Startup time**: Should be <1 second (module imports are lazy if possible)
- **Per-call overhead**: <50ms for wrapper routing/parsing
- **Module execution**: Depends on module, timeout enforced
- **Memory**: Each module loaded once, stays in memory
- **Concurrency**: Wrapper processes one request at a time (sequential)

## 8. Security Considerations

- **Input validation**: Wrapper validates JSON-RPC schema; modules validate arguments
- **No arbitrary code execution**: Tools are predefined, not dynamic
- **API keys**: Module responsibility to load from env vars, not hardcode
- **Isolation**: Each module is independent; failures don't affect others
- **Timeout protection**: Prevents infinite loops
- **Error messages**: Don't leak sensitive info in error responses
