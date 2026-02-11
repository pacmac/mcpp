# MCP Tool Integration - Postmortem & Critical Requirements

**Date**: 2026-02-08
**Project**: mcpp (stdio MCP server wrapper)
**Issue**: MCP server connected but tools were invisible to Claude Code
**Status**: ✅ RESOLVED

---

## Executive Summary

The mcpp MCP server was properly configured and connected, but its tools were invisible to Claude Code. The root cause was a missing capability declaration in the MCP protocol `initialize` response. This postmortem documents the **critical requirements** that MUST be met for any MCP tool server to work.

**UPDATE (2026-02-08)**: After extensive investigation, discovered the **correct way** to configure MCP servers globally is using the Claude CLI with `--scope user` flag, NOT manual config file editing.

---

## ⭐ THE SOLUTION: Use --scope user

**The correct command to configure MCP servers globally:**

```bash
claude mcp add mcpp --scope user \
  --env MCPP_LOG_LEVEL=error \
  --env MCPP_TIMEOUT_SECONDS=30 \
  -- python3 /usr/share/pac/dev/py/mcpp/wrapper.py
```

**Why this matters:**
- `--scope user` adds MCP server to `~/.claude/settings.json` in the correct location
- Works globally across ALL directories without per-project configuration
- No conflicts with Claude Code's auto-project-creation behavior
- No need to manually edit config files or fight with configuration hierarchy

**What we learned the hard way:**
1. ❌ Manually editing `~/.claude/settings.json` doesn't set proper scope
2. ❌ Per-project config in `/root/.claude.json` overrides global config
3. ❌ Claude Code auto-creates project entries with empty `mcpServers: {}`, blocking global config
4. ✅ Using `claude mcp add --scope user` is the ONLY reliable way to configure global MCP servers

**Cleanup after manual configuration attempts:**
If you previously tried manual config, remove old definitions:
- Remove mcpp from top-level `mcpServers` in `/root/.claude.json`
- Remove mcpp from per-project `mcpServers` in `/root/.claude.json` projects
- The user-scoped definition in `~/.claude/settings.json` will take precedence

---

## The Critical Requirements Checklist

### ✅ MANDATORY: MCP Protocol Implementation

For a stdio MCP server to expose tools to Claude Code, these requirements are **NON-NEGOTIABLE**:

#### 1. **Declare "tools" Capability in Initialize Response**
```python
# ❌ WRONG - Tools will be invisible
{
    "protocolVersion": "2024-11-05",
    "capabilities": {},  # Empty = no tools!
    "serverInfo": {...}
}

# ✅ CORRECT - Tools will be discovered
{
    "protocolVersion": "2024-11-05",
    "capabilities": {
        "tools": {}  # Declares server provides tools
    },
    "serverInfo": {...}
}
```

**Location**: Initialize method handler (wrapper.py line 296)
**Impact**: Without this, Claude Code never calls `tools/list` and never discovers your tools
**Symptom**: Server shows "✔ connected" but no `mcp__servername__*` tools appear

#### 2. **Implement tools/list Method**
```python
if method == "tools/list":
    return _jsonrpc_response(
        id_,
        result={
            "tools": [
                {
                    "name": "tool_name",
                    "description": "What the tool does",
                    "inputSchema": {
                        "type": "object",
                        "properties": {...},
                        "required": [...]
                    }
                }
            ]
        }
    )
```

**Must return**: Array of tool definitions with name, description, and JSON schema
**Called**: After initialize succeeds, if "tools" capability was declared
**Tool naming**: Use simple names like `fetch_page`, Claude Code prefixes with `mcp__servername__`

#### 3. **Implement tools/call Method**
```python
if method == "tools/call":
    tool_name = params["name"]
    tool_args = params.get("arguments", {})

    # Execute the tool
    result = execute_tool(tool_name, tool_args)

    return _jsonrpc_response(
        id_,
        result={
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result)
                }
            ]
        }
    )
```

**Must handle**: Tool execution with provided arguments
**Must return**: Content array with results (typically JSON as text)
**Error handling**: Return proper JSON-RPC error responses for failures

#### 4. **stdio Protocol Compliance**
```python
# Read JSON-RPC requests from stdin
for line in sys.stdin:
    request = json.loads(line)
    response = handle_request(request)

    # Write JSON-RPC responses to stdout
    print(json.dumps(response), flush=True)
```

**Critical**: One JSON object per line, flushed immediately
**No extra output**: Logging must go to stderr or file, never stdout
**Buffering**: Always flush stdout after writing response

---

## Configuration Requirements

### Global Configuration (✅ USE --scope user)

**CORRECT METHOD:**
```bash
claude mcp add servername --scope user \
  --env VAR=value \
  -- command args
```

**Why this works:**
- Sets proper user scope in `~/.claude/settings.json`
- Applies globally across all directories
- No per-project configuration needed
- No conflicts with auto-created project entries

**WRONG METHOD (Don't do this):**
- Manually editing `~/.claude/settings.json` - doesn't set proper scope
- Manually editing `/root/.claude.json` - gets overridden by per-project entries
- Per-project configuration - defeats the purpose of global config

### ⚠️ CRITICAL: Global Config Doesn't Work

**VERDICT**: Global MCP configuration is fundamentally incompatible with Claude Code's behavior.

**Why global config fails**:
- Claude Code auto-creates a project entry when starting from ANY directory
- New project entries have `"mcpServers": {}` by default
- Empty `"mcpServers": {}` overrides and blocks global config
- Even brand new folders get auto-created entries that block global config

**Configuration Hierarchy**:
1. **Per-project** (`/root/.claude.json` projects section) - highest priority
2. **Global** (`~/.claude/settings.json`) - fallback

**The Trap**:
```json
// /root/.claude.json
{
  "projects": {
    "/tmp": {
      "mcpServers": {}  // ❌ Empty object blocks global mcpp config!
    }
  }
}
```

When you start Claude Code from `/tmp`, it checks:
1. Does `/tmp` exist in projects? → Yes
2. Does it have mcpServers defined? → Yes (empty object)
3. Result: Use project's mcpServers (empty), ignore global config

**ONLY Working Solution**: Add mcpp to per-project mcpServers for each directory you use:
```json
// Add mcpp to each project's mcpServers section
{
  "projects": {
    "/tmp": {
      "mcpServers": {
        "mcpp": {
          "type": "stdio",
          "command": "python3",
          "args": ["/usr/share/pac/dev/py/mcpp/wrapper.py"]
        }
      }
    }
  }
}
```

### Per-Project Configuration (Optional)
**File**: `/root/.claude.json` or project-specific `.claude.json`

```json
{
  "projects": {
    "/path/to/project": {
      "mcpServers": {
        "servername": {...}
      },
      "allowedTools": [
        "mcp__servername__*"
      ]
    }
  }
}
```

**Use case**: Override global config or pre-approve specific tools
**Not required**: If global config exists, it inherits automatically

---

## What Happened (Timeline)

### Initial State
- ✅ Global config existed in `~/.claude/settings.json`
- ✅ wrapper.py loaded and executed correctly
- ✅ 6 tools discovered from 3 modules
- ✅ MCP connection showed "✔ connected"
- ❌ Tools were invisible to Claude Code

### Investigation
1. Verified global config - correct
2. Verified wrapper.py execution - correct
3. Verified MCP connection status - connected
4. Checked available tools - none with `mcp__mcpp__*` prefix
5. **Found root cause**: Line 296 had `"capabilities": {}`

### Root Cause
```python
# wrapper.py line 291-298 (BEFORE FIX)
if method == "initialize":
    return _jsonrpc_response(
        id_,
        result={
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},  # ❌ BUG: Missing "tools" declaration
            "serverInfo": SERVER_INFO,
        },
    )
```

**Why this breaks**:
- Claude Code respects capability negotiation
- Server says "I have no capabilities"
- Claude Code never calls `tools/list`
- Tools never get registered

### The Fix
```python
# wrapper.py line 291-298 (AFTER FIX)
if method == "initialize":
    return _jsonrpc_response(
        id_,
        result={
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {}  # ✅ FIX: Declare tools capability
            },
            "serverInfo": SERVER_INFO,
        },
    )
```

### Verification
1. Applied fix to wrapper.py
2. Restarted Claude Code session (required to reconnect)
3. User asked: "Fetch the page https://example.com"
4. Claude automatically used `mcp__mcpp__fetch_page` tool
5. Tool executed successfully
6. ✅ **FIX CONFIRMED**

---

## Key Lessons Learned

### 1. Connection ≠ Tool Availability
- "✔ connected" only means stdio transport works
- Doesn't mean tools are registered or visible
- Must verify tools appear in available tools list

### 2. Capability Declaration is Mandatory
- Empty capabilities = server provides nothing
- Must explicitly declare `"tools": {}` to expose tools
- Protocol spec is strict about capability negotiation

### 3. Test Tool Visibility, Not Just Connection
**Wrong test**: Check if `/mcp` shows connected
**Right test**: Try to actually use a tool

### 4. Debug Path for "Connected but No Tools"
1. Check `initialize` response has `"capabilities": {"tools": {}}`
2. Check `tools/list` method exists and returns valid schemas
3. Check tool names don't conflict with built-in tools
4. Check Claude Code logs for registration errors

---

## Reference: Working MCP Server Skeleton

```python
#!/usr/bin/env python3
import sys
import json

PROTOCOL_VERSION = "2024-11-05"

def handle_request(request):
    method = request.get("method")
    params = request.get("params", {})
    id_ = request.get("id")

    # 1. CRITICAL: Declare capabilities
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": id_,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {}  # MUST declare this!
                },
                "serverInfo": {
                    "name": "my-server",
                    "version": "1.0.0"
                }
            }
        }

    # 2. Return tool definitions
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": id_,
            "result": {
                "tools": [
                    {
                        "name": "my_tool",
                        "description": "Does something useful",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "param": {"type": "string"}
                            },
                            "required": ["param"]
                        }
                    }
                ]
            }
        }

    # 3. Execute tools
    if method == "tools/call":
        tool_name = params["name"]
        tool_args = params.get("arguments", {})

        # Your tool logic here
        result = {"status": "success"}

        return {
            "jsonrpc": "2.0",
            "id": id_,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result)
                    }
                ]
            }
        }

    return {
        "jsonrpc": "2.0",
        "id": id_,
        "error": {
            "code": -32601,
            "message": f"Unknown method: {method}"
        }
    }

if __name__ == "__main__":
    for line in sys.stdin:
        request = json.loads(line)
        response = handle_request(request)
        print(json.dumps(response), flush=True)  # MUST flush!
```

---

## Quick Diagnosis Guide

**Symptom**: MCP server shows "✔ connected" but tools are invisible

**Check (in order)**:
1. ✅ Does `initialize` response include `"capabilities": {"tools": {}}`?
2. ✅ Does `tools/list` method exist and return tool schemas?
3. ✅ Does `tools/call` method exist and handle execution?
4. ✅ Is stdout reserved for JSON-RPC only (no logging)?
5. ✅ Are responses flushed immediately after writing?
6. ✅ Did you restart Claude Code after changing wrapper code?

**Fix**: Add missing capability declaration, restart session, verify tools appear

---

## Workspace Directory Mechanism

### How workspace_dir Works

**Implementation** (wrapper.py:382):
```python
workspace_dir = str(Path.cwd().resolve())
```

**Execution flow:**
1. Claude Code starts from directory `/project-a/`
2. Launches MCP server: `python3 /path/to/wrapper.py`
3. Wrapper captures `Path.cwd()` at startup → `/project-a/`
4. All tool calls receive this workspace_dir in context

**Design principle** (SPEC.md:153):
> "The wrapper is designed to be **on-demand per workspace**: one wrapper process serves one workspace directory."

### Critical Assumptions

The current implementation assumes:
1. ✅ Claude Code launches a NEW wrapper process per session
2. ✅ The wrapper inherits Claude Code's current working directory
3. ✅ workspace_dir remains stable for the session duration (no chdir)

### Potential Issues

**If Claude Code reuses wrapper processes across sessions:**
- Starting Claude Code from `/project-a/` → workspace_dir = `/project-a/` ✅
- Later, starting from `/project-b/` → workspace_dir still `/project-a/` ❌
- Tools would operate on wrong directory!

### Verification Status

✅ **Verified for current session**: workspace_dir matches Claude Code startup directory
⏸️ **Cross-session behavior**: Needs testing (see Verification Procedure below)

### Safeguards Available

If cross-session testing reveals issues, add environment variable override:

```python
# wrapper.py line 382
workspace_dir = os.getenv("MCPP_WORKSPACE_DIR")
if not workspace_dir:
    workspace_dir = str(Path.cwd().resolve())
```

Then configure per-project in `.claude.json`:
```json
{
  "projects": {
    "/specific/project": {
      "mcpServers": {
        "mcpp": {
          "type": "stdio",
          "command": "python3",
          "args": ["/usr/share/pac/dev/py/mcpp/wrapper.py"],
          "env": {
            "MCPP_WORKSPACE_DIR": "/specific/project"
          }
        }
      }
    }
  }
}
```

---

## Verification Procedure

### Test 1: Tool Visibility (✅ PASSED 2026-02-08)

**Purpose**: Verify MCP server declares capabilities and tools are visible

**Steps:**
1. Start Claude Code in any directory
2. Ask: "fetch the page https://example.com"
3. Verify Claude automatically uses `mcp__mcpp__fetch_page` tool

**Expected**: Tool executes without needing to be told it exists
**Status**: ✅ PASSED - tools are visible and auto-discovered

### Test 2: Current Session Workspace (✅ PASSED 2026-02-08)

**Purpose**: Verify workspace_dir matches current session directory

**Steps:**
1. Start Claude Code in `/usr/share/pac/dev/py/mcpp`
2. Ask: "use scaffold_where to show workspace_dir"
3. Compare result to `pwd`

**Expected**: workspace_dir = `/usr/share/pac/dev/py/mcpp`
**Status**: ✅ PASSED - workspace_dir correctly captured

### Test 3: Cross-Session Workspace (⏸️ PENDING)

**Purpose**: Verify workspace_dir updates when starting from different directories

**Steps:**
1. **Exit Claude Code completely** (don't just cd within session)
2. **Start fresh session from different directory**:
   ```bash
   cd /tmp
   claude-code
   ```
3. **Verify workspace_dir**:
   - Ask: "use scaffold_where to show workspace_dir"
   - Expected: `{"workspace_dir": "/tmp", ...}`
4. **Test write operation**:
   - Ask: "create a directory called test-mcpp-verification"
   - Expected: Directory created in `/tmp/test-mcpp-verification`
   - Verify: `ls -la /tmp/test-mcpp-verification`
5. **Cleanup**:
   ```bash
   rm -rf /tmp/test-mcpp-verification
   ```

**Expected Results:**
- workspace_dir = `/tmp` (not previous session's directory)
- Directory created in correct location
- Tools operate relative to new workspace

**If Test FAILS** (workspace_dir stuck at old location):
- Indicates Claude Code reuses wrapper processes
- Must implement `MCPP_WORKSPACE_DIR` environment variable override
- Document limitation for multi-project workflows

### Test 4: Multi-Project Workflow (⏸️ PENDING)

**Purpose**: Verify workflow when frequently switching between projects

**Steps:**
1. Start Claude Code in `/project-a/`
2. Use mcpp tools to create files
3. Exit and start Claude Code in `/project-b/`
4. Use mcpp tools to create files
5. Verify files created in correct project directories

**Expected**: Each session operates on its own workspace independently

---

## Conclusion

**THE THREE CRITICAL THINGS FOR MCP SERVERS:**

### 1. Configuration: Use --scope user (MOST IMPORTANT)

```bash
claude mcp add servername --scope user --env VAR=value -- command args
```

**This is the ONLY reliable way** to configure MCP servers globally. Manual config editing leads to conflicts with Claude Code's auto-project-creation behavior. This discovery came after hours of debugging configuration hierarchy issues.

### 2. Protocol: Declare tools capability

```python
"capabilities": {
    "tools": {}
}
```

Without this in your `initialize` response, your MCP server will appear connected but provide zero functionality. This is the #1 mistake when implementing MCP tool servers.

### 3. Context: Verify workspace_dir

Verify your workspace_dir mechanism works correctly across different project directories. Test by starting your agent from different folders and confirming tools operate on the correct workspace.

**Remember**:
- Use `--scope user` for global config (don't manually edit files)
- Connected ≠ Working (test tool visibility)
- Visible ≠ Correct Context (test workspace_dir)

Always verify configuration scope, tool availability, AND workspace context before deploying to production workflows.
