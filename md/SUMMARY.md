# Project Summary: mcpp

## Overview
**mcpp** (Model Context Protocol Python) is a lightweight, immutable MCP server designed to bridge CLI agents (like Claude Code) with local Python tools. It acts as a standardized "on-demand" wrapper that routes JSON-RPC requests from standard input to dynamically discovered modules.

## Key Architecture

### 1. The Wrapper (`mcpp.py`)
- **Role:** The core server daemon.
- **Function:** 
  - Listens for JSON-RPC 2.0 messages on `stdin`.
  - Discovers and loads Python modules from the `tools/` directory.
  - Routes `tools/call` requests to the appropriate module's `execute()` function.
  - Handles protocol compliance, error reporting, and timeouts.
- **Design Principle:** "Immutable Infrastructure" — the wrapper logic rarely changes; functionality is expanded solely by adding new modules.

### 2. Extensibility (`tools/`)
- **Mechanism:** Drop-in extensibility. No registry edits required.
- **Format:** Supports single-file modules (`tools/weather.py`) or package-style modules (`tools/weather/main.py`).
- **Contract:** Modules must export:
  - `MODULE_NAME`: Unique identifier.
  - `TOOLS`: List of MCP tool schemas.
  - `execute(tool_name, args, context)`: The implementation logic.
- **Context Awareness:** Modules receive a `context` dict containing `workspace_dir` (where the wrapper started) and `module_scope` (local vs. global), allowing for flexible path resolution.

### 3. Human Interface (`cli.py`)
- **Role:** A command-line client for developers.
- **Usage:** Allows manual invocation of tools (e.g., `python3 cli.py call fetch_page --url ...`).
- **Benefit:** Facilitates testing, debugging, and scripting without requiring a full AI agent session.

## Current Status

- **Implementation:** Core wrapper (`mcpp.py`) and basic tools (`what`, `fetch_page`, `spi`) appear implemented.
- **Documentation:** Comprehensive specs available in `md/SCOPE.md`, `SPEC.md`, and `IMPLEMENT.md`.
- **Naming:** The directory is `mcpp`, and documentation has been updated to match.
- **Testing:** A test suite exists in `tests/` covering cache, protocol, and wrapper logic.

## Next Steps (inferred from TASKS.md)
1. **Standardize Naming:** Update documentation and config to match the chosen project name (likely `mcpp` given the file structure).
2. **Verify CLI Targets:** Ensure the wrapper supports other CLIs beyond the initial target (Codex/Claude).
