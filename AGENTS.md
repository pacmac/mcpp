# AGENTS.md (Token-Sparing Workflow)

## Goal

Build an **on-demand stdio MCP server wrapper** plus **pluggable Python tool modules**, while minimizing context/tokens by reading only what is necessary.

## Read Order (Do Not Bulk-Read Files)

1. `TASKS.md` (work state and next step)
2. `SPEC.md` (only the section needed for the task at hand)
3. `IMPLEMENT.md` (only when you need invocation/examples)
4. `SCOPE.md` (only when deciding if something is in/out of scope)

Avoid opening whole docs unless you are actively editing them.

## Context Hygiene Rules

- Prefer `rg -n 'pattern' *.md` to locate the exact section to open.
- Prefer `sed -n 'START,ENDp' file` to read only the lines you need.
- When changing code, read only the relevant file(s) and minimal surrounding context.
- Do not “sync context” by rereading all docs.

## Non-Negotiable Requirements

- Wrapper is a **stdio MCP server** (JSON-RPC over stdin/stdout).
- Wrapper should be treated as **infrastructure**: extend via modules in `tools/`, not wrapper edits.
- Each module is **either** `local` **or** `global` (`MODULE_SCOPE`), no mixing within a module.
- Wrapper passes `context` into module calls:
  - `workspace_dir`: absolute wrapper startup `cwd` (caller folder)
  - `module_dir`: absolute module directory
  - `module_scope`: resolved `local|global`
- Wrapper must not `chdir` at runtime; `workspace_dir` must remain stable.

## Where To Record Progress

Use `TASKS.md` as the only work tracker.

- Start work: move an item from `TODO` to `Doing`.
- Finish work: move it to `Done` only after the relevant **Testing Phase** bullet(s) pass.
- Add new work: append to `TODO`.

Keep `IMPLEMENT.md` as “how to use”, not a worklog.

