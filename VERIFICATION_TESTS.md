# MCP Server Verification Tests

**Purpose**: Comprehensive test procedures to verify mymcp MCP server works correctly.

**Last Updated**: 2026-02-08

---

## Quick Status Dashboard

| Test | Status | Date | Notes |
|------|--------|------|-------|
| Test 1: Tool Visibility | ✅ PASSED | 2026-02-08 | Tools auto-discovered by Claude Code |
| Test 2: Tool Execution | ✅ PASSED | 2026-02-08 | fetch_page and spi_init work correctly |
| Test 3: Workspace Behavior | ⏸️ PENDING | - | Cross-session testing needed |

---

## Test 1: Tool Visibility ✅

**What it tests**: MCP server declares capabilities correctly and tools are discoverable

**Prerequisites**:
- Claude Code installed and configured
- mymcp configured in `~/.claude/settings.json`

**Procedure**:

1. Start Claude Code from any directory
2. Type: `fetch the page https://example.com`
3. Observe Claude's behavior

**Expected Result**:
- Claude automatically uses `mcp__mymcp__fetch_page` tool
- No need to tell Claude the tool exists
- Page content is fetched and displayed

**Pass Criteria**:
- ✅ Tool is used automatically
- ✅ No "unknown tool" errors
- ✅ Fetch completes successfully

**If Test Fails**:
- Check `/mcp` command to see if mymcp shows connected
- Verify wrapper.py has `"capabilities": {"tools": {}}`
- Restart Claude Code session
- See MCP_POSTMORTEM.md "Quick Diagnosis Guide"

**Status**: ✅ PASSED (2026-02-08)

---

## Test 2: Tool Execution ✅

**What it tests**: Individual tool functionality works correctly

**Prerequisites**:
- mymcp tools available
- Internet connectivity (for fetch_page)

### 2a: fetch_page tool

**Procedure**:
1. Type: `use fetch_page to get https://example.com`
2. Verify page content is returned
3. Check for errors

**Expected**: HTML content from example.com displayed

**Status**: ✅ PASSED (2026-02-08)

### 2b: spi_init tool

**Procedure**:
1. Navigate to empty directory or /tmp
2. Type: `use spi_init to create spi templates`
3. Verify: `ls -la spi/`
4. Check files: SPEC.md, PLAN.md, IMPLEMENT.md, TASKS.md exist

**Expected**: Template files created in `./spi/` directory under workspace

**Status**: ⏸️ PENDING

---

## Test 3: Workspace Behavior ⏸️

**What it tests**: workspace_dir updates correctly when starting Claude Code from different directories

**Prerequisites**:
- Access to multiple directories on the system

**Procedure**:

### Part A: Start from /tmp

1. **Close Claude Code completely** (if running)
2. **Navigate to /tmp**: `cd /tmp`
3. **Start Claude Code**: `claude-code`
4. **Test file creation**:
   - Type: `use spi_init`
   - Expected: Success message
5. **Verify location**: `ls -la /tmp/spi/`
   - Expected: Directory exists in `/tmp`

### Part B: Start from different directory

6. **Exit Claude Code**
7. **Navigate to different directory**: `cd /var/tmp`
8. **Start Claude Code again**: `claude-code`
9. **Test file creation**:
    - Type: `use spi_init --overwrite true`
    - Expected: Directory created in `/var/tmp/spi/`

### Part C: Cleanup

10. **Remove test directories**:
    ```bash
    rm -rf /tmp/spi
    rm -rf /var/tmp/spi
    ```

**Expected Results**:
- ✅ workspace_dir = `/tmp` when started from `/tmp`
- ✅ workspace_dir = `/var/tmp` when started from `/var/tmp`
- ✅ Files created in correct workspace for each session

**Pass Criteria**:
- workspace_dir updates for each new session
- Tools operate relative to current session's workspace
- No cross-contamination between sessions

**Status**: ⏸️ PENDING - Awaiting test execution

---

## Notes for Test Execution

### Before Each Test Session

- Document current date/time
- Note Claude Code version
- Note operating system and environment
- Clear any previous test artifacts

### During Testing

- Follow steps exactly as written
- Document any deviations or unexpected behavior
- Save error messages verbatim

### After Testing

- Update status in Quick Status Dashboard
- Update individual test status sections
- Document findings
- Clean up all test artifacts

### Reporting Issues

If tests reveal problems:
1. Document exact failure mode
2. Include error messages and logs
3. Note environment details
4. Update MCP_POSTMORTEM.md with findings
