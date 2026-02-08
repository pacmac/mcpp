# MCP Stdio On-Demand Agent Wrapper - Implementation Notes

This document contains practical invocation, layout, and examples. The behavioral contracts are defined in `SPEC.md`, and the high-level project scope is in `SCOPE.md`.

## 1. Wrapper Usage

### 1.1 Invocation
```bash
python3 wrapper.py
```

The wrapper reads from stdin and writes to stdout. No command-line arguments needed.

### 1.2 Environment Variables

Supported env vars:
- `MYMPC_MODULES_PATH`: tools directory (default: `tools`)
- `MYMPC_LOG_LEVEL`: `debug|info|warning|error` (default: `info`)
- `MYMPC_TIMEOUT_SECONDS`: per-tool timeout in seconds (default: `30`)

### 1.3 Agent Integration

Agent CLIs invoke the wrapper as an MCP stdio server.

```bash
# Example: custom agent
my-agent --tools-server "python3 /path/to/wrapper.py"
```

The agent sends MCP messages via stdin, receives responses via stdout.

#### 1.3.1 Codex CLI Config (TOML)

Codex CLI reads `~/.codex/config.toml`. Add:

```toml
[mcp_servers.mympc]
command = "python3"
args = ["/usr/share/pac/dev/py/mympc/wrapper.py"]
env = { MYMPC_LOG_LEVEL = "error", MYMPC_TIMEOUT_SECONDS = "30" }
```

Verify Codex sees it:

```bash
codex mcp list
codex mcp get mympc
```

**Workspace note (important for `local` tools):**
- `workspace_dir` is the wrapper process startup working directory.
- To make tools operate “on the folder it is called from”, run the agent from that folder, or use `codex -C /path/to/workspace` (sets the agent workspace).
- If your client cannot set server `cwd`, wrap the command: `bash -lc 'cd /path/to/workspace && python3 wrapper.py'`.

## 2. Adding and Testing Modules

### 2.1 Adding a New Tool

To add a new tool, create `tools/<module_name>/main.py`:

```python
MODULE_NAME = "mytool"
MODULE_SCOPE = "local"  # or "global"

TOOLS = [
    {
        "name": "my_function",
        "description": "Does something useful",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input": {"type": "string"}
            },
            "required": ["input"]
        }
    }
]

def execute(tool_name: str, arguments: dict, context: dict | None = None) -> dict:
    try:
        if tool_name == "my_function":
            # For local modules, this is the wrapper startup cwd.
            # For global modules, you may instead use Path(__file__).parent.
            workspace_dir = (context or {}).get("workspace_dir")
            result = some_logic(arguments["input"])
            return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

**That's it.** No wrapper changes needed. Restart wrapper, new tool is available.

### 2.1.2 Directory (Package-Style) Modules

All modules are directory modules. Put the entrypoint at:

- `tools/<module_name>/main.py` (entry point)
- any sibling files under `tools/<module_name>/` (e.g. `helper.py`, `data.json`)

The wrapper loads `main.py` as a package module, so relative imports like `from .helper import X` work.

### 2.1.1 Scope Examples

**Global module (service-like): fetch a page**
- `MODULE_SCOPE = "global"`
- Bundled data lives under `module_dir` (parsers, prompts, static config).
- Behavior does not depend on which workspace launched the wrapper.

**Local module (workspace mutator): scaffold files/folders**
- `MODULE_SCOPE = "local"`
- Treat `context["workspace_dir"]` as the root for all relative paths.
- Create folders/files under that workspace directory.

### 2.2 Module Testing

Each module can be tested independently:

```python
# test_mytool.py
from tools.mytool import execute, TOOLS

def test_my_function():
    result = execute("my_function", {"input": "test"}, {"workspace_dir": ".", "module_dir": "tools", "module_scope": "local"})
    assert result["success"] == True
    assert "result" in result
```

## 3. Example Modules

### Example 1: Calculator Module
```python
MODULE_NAME = "calculator"
TOOLS = [
    {
        "name": "add",
        "description": "Add two numbers",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"}
            },
            "required": ["a", "b"]
        }
    }
]

def execute(tool_name: str, arguments: dict) -> dict:
    try:
        if tool_name == "add":
            return {"success": True, "result": arguments["a"] + arguments["b"]}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

### Example 2: File Operations Module
```python
MODULE_NAME = "file_ops"
TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write to a file",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    }
]

def execute(tool_name: str, arguments: dict) -> dict:
    try:
        if tool_name == "read_file":
            with open(arguments["path"]) as f:
                return {"success": True, "result": f.read()}
        elif tool_name == "write_file":
            with open(arguments["path"], "w") as f:
                f.write(arguments["content"])
            return {"success": True, "result": "Written"}
    except Exception as e:
        return {"success": False, "error": str(e)}
```
