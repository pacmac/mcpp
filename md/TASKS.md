# Tasks

Work tracker for this repo. Keep `SCOPE.md`, `SPEC.md`, and `IMPLEMENT.md` as reference docs; track execution here.

## TODO
- **MCP Specification Compliance Audit**: Document gaps and plan upgrades
  - Current protocol version: 2024-11-05 (8+ months behind latest 2025-11-25)
  - Missing features: structured outputs, progress notifications, version negotiation
  - See `§9 MCP Specification Compliance` in SPEC.md for details
  - Priority items: (1) update to 2025-06-18, (2) implement version negotiation, (3) structured outputs

- (passed) Protocol lifecycle smoke test: `initialize` -> `notifications/initialized` (ignored) -> `tools/list` -> `tools/call` -> `shutdown` -> `exit`
- (passed) Tool result conformance tests: `content[]`, `isError`, and protocol-level JSON-RPC errors
- (passed) Module discovery tests: bad import, missing exports, duplicate tool names, optional `initialize()`
- (passed) Workspace context tests: `workspace_dir` is stable and passed to local modules; wrapper never `chdir`
- (passed) Compatibility run against Codex CLI in stdio mode (tool calls succeed)
- **Fixed Test Suite Inconsistencies**: Aligned `tests/` with `mcpp` architecture.
  - Updated `wrapper.py` references to `mcpp.py`
  - Fixed imports from `wrapper` to `mcpp`
  - Updated environment variables from `MYMPC_` to `MCPP_`
  - Removed obsolete `scaffold_*` tool references (scaffold module was intentionally removed)

## Doing
- (empty)

## Done
- **Fix directory typo**: Rename `/usr/share/pac/dev/py/mympc/` → `/usr/share/pac/dev/py/mcpp/` (completed)
  - Update bash wrapper path in `/usr/share/pac/dev/py/mycli`
  - Update MCP server config in `~/.claude/settings.json` (mcpp.py path)
  - Update MCP server config in `/root/.claude.json` if exists
  - Update all documentation (SPEC.md, IMPLEMENT.md, SCOPE.md, CLAUDEMCP.md, MCP_POSTMORTEM.md, VERIFICATION_TESTS.md)
  - Restart Claude Code after config changes
  - Git repository moves with directory
- Confirm minimum MCP surface area required by additional target CLIs (beyond Codex CLI)
- Split docs into `SCOPE.md`, `SPEC.md`, `IMPLEMENT.md`
- Add forward-planning `MODULE_SCOPE` + `context` contract to docs
- Document global vs local examples (fetcher vs scaffolder) and path resolution policy
- Implement immutable MCP stdio wrapper (JSON-RPC read/parse/respond)
- Implement module discovery/loading from `tools/` directory
- Enforce tool name uniqueness + module validation
- Implement `tools/list`, `tools/call`, `initialize`, notifications handling, plus `shutdown`/`exit`
- Add per-call `context` injection (`workspace_dir`, `module_dir`, `module_scope`)
- Add timeout handling per tool call
- Add logging (startup summary, per-call timing, errors)
