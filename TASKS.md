# Tasks

Work tracker for this repo. Keep `SCOPE.md`, `SPEC.md`, and `IMPLEMENT.md` as reference docs; track execution here.

## TODO
- Confirm minimum MCP surface area required by additional target CLIs (beyond Codex CLI)

## Testing Phase
- (passed) Protocol lifecycle smoke test: `initialize` -> `notifications/initialized` (ignored) -> `tools/list` -> `tools/call` -> `shutdown` -> `exit`
- (passed) Tool result conformance tests: `content[]`, `isError`, and protocol-level JSON-RPC errors
- (passed) Module discovery tests: bad import, missing exports, duplicate tool names, optional `initialize()`
- (passed) Workspace context tests: `workspace_dir` is stable and passed to local modules; wrapper never `chdir`
- (passed) Compatibility run against Codex CLI in stdio mode (tool calls succeed)

## Doing
- (empty)

## Done
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
