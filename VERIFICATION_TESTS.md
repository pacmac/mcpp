# MCP Server Verification Tests

**Purpose**: Comprehensive test procedures to verify mympc MCP server works correctly across different scenarios.

**Last Updated**: 2026-02-08

---

## Quick Status Dashboard

| Test | Status | Date | Notes |
|------|--------|------|-------|
| Test 1: Tool Visibility | ✅ PASSED | 2026-02-08 | Tools auto-discovered by Claude Code |
| Test 2: Current Session Workspace | ✅ PASSED | 2026-02-08 | workspace_dir matches startup directory |
| Test 3: Cross-Session Workspace | ⏸️ PENDING | - | Not yet tested |
| Test 4: Multi-Project Workflow | ⏸️ PENDING | - | Not yet tested |
| Test 5: Tool Execution | ✅ PASSED | 2026-02-08 | fetch_page executed successfully |

---

## Test 1: Tool Visibility ✅

**What it tests**: MCP server declares capabilities correctly and tools are discoverable

**Prerequisites**:
- Claude Code installed and configured
- mympc configured in `~/.claude/settings.json`

**Procedure**:

1. Start Claude Code from any directory
2. Type: `fetch the page https://example.com`
3. Observe Claude's behavior

**Expected Result**:
- Claude automatically uses `mcp__mympc__fetch_page` tool
- No need to tell Claude the tool exists
- Page content is fetched and displayed

**Pass Criteria**:
- ✅ Tool is used automatically
- ✅ No "unknown tool" errors
- ✅ Fetch completes successfully

**If Test Fails**:
- Check `/mcp` command to see if mympc shows connected
- Verify wrapper.py line 296 has `"capabilities": {"tools": {}}`
- Restart Claude Code session
- See MCP_POSTMORTEM.md "Quick Diagnosis Guide"

**Status**: ✅ PASSED (2026-02-08)

---

## Test 2: Current Session Workspace ✅

**What it tests**: workspace_dir correctly captures the directory where Claude Code was started

**Prerequisites**:
- Claude Code running
- mympc tools available

**Procedure**:

1. Note the directory where Claude Code was started (check system prompt or use `pwd`)
2. Type: `use scaffold_where to show workspace_dir`
3. Compare the `workspace_dir` value to the startup directory

**Expected Result**:
```json
{
  "workspace_dir": "/path/where/claude-code/started",
  "module_dir": "/usr/share/pac/dev/py/mympc/tools/scaffold",
  "module_scope": "local"
}
```

**Pass Criteria**:
- ✅ workspace_dir matches Claude Code startup directory
- ✅ Path is absolute (not relative)
- ✅ Path is resolved (symlinks followed to canonical path)

**If Test Fails**:
- Check wrapper.py line 382: should capture `Path.cwd().resolve()`
- Verify Claude Code doesn't chdir before launching MCP server
- Check if environment variable `MYMPC_WORKSPACE_DIR` is overriding

**Status**: ✅ PASSED (2026-02-08)
- Tested in `/usr/share/pac/dev/py/mympc`
- workspace_dir correctly reported as `/usr/share/pac/dev/py/mympc`

---

## Test 3: Cross-Session Workspace ⏸️

**What it tests**: workspace_dir updates correctly when starting Claude Code from different directories

**Prerequisites**:
- Access to multiple directories on the system
- Permission to create test files in `/tmp`

**Procedure**:

### Part A: Start from /tmp

1. **Close Claude Code completely** (if running)
2. **Navigate to /tmp**:
   ```bash
   cd /tmp
   ```
3. **Start Claude Code**:
   ```bash
   claude-code
   ```
4. **Verify workspace_dir**:
   - Type: `use scaffold_where to show workspace_dir`
   - Expected: `{"workspace_dir": "/tmp", ...}`

5. **Test file creation**:
   - Type: `use scaffold_mkdir to create a directory called test-mympc-verification`
   - Expected: Success message

6. **Verify location**:
   - Type: `ls -la /tmp/test-mympc-verification`
   - Expected: Directory exists in `/tmp`

### Part B: Start from different directory

7. **Exit Claude Code**
8. **Navigate to different directory**:
   ```bash
   cd /var/tmp
   ```
9. **Start Claude Code again**:
   ```bash
   claude-code
   ```
10. **Verify workspace_dir changed**:
    - Type: `use scaffold_where to show workspace_dir`
    - Expected: `{"workspace_dir": "/var/tmp", ...}`

11. **Test file creation**:
    - Type: `use scaffold_mkdir to create a directory called test-mympc-verification-2`
    - Expected: Directory created in `/var/tmp/test-mympc-verification-2`

### Part C: Cleanup

12. **Remove test directories**:
    ```bash
    rm -rf /tmp/test-mympc-verification
    rm -rf /var/tmp/test-mympc-verification-2
    ```

**Expected Results**:
- ✅ workspace_dir = `/tmp` when started from `/tmp`
- ✅ workspace_dir = `/var/tmp` when started from `/var/tmp`
- ✅ Files created in correct workspace for each session
- ✅ Each session operates independently

**Pass Criteria**:
- workspace_dir updates for each new session
- Tools operate relative to current session's workspace
- No cross-contamination between sessions

**If Test FAILS** (workspace_dir doesn't change):

This indicates Claude Code reuses the wrapper process across sessions. You need to implement the environment variable override:

1. **Add to wrapper.py line 382**:
   ```python
   workspace_dir = os.getenv("MYMPC_WORKSPACE_DIR")
   if not workspace_dir:
       workspace_dir = str(Path.cwd().resolve())
   ```

2. **Configure per-project** in `.claude.json`:
   ```json
   {
     "projects": {
       "/tmp": {
         "mcpServers": {
           "mympc": {
             "env": {
               "MYMPC_WORKSPACE_DIR": "/tmp"
             }
           }
         }
       }
     }
   }
   ```

3. **Document limitation** in README.md

**Status**: ⏸️ PENDING - Awaiting test execution

---

## Test 4: Multi-Project Workflow ⏸️

**What it tests**: Realistic workflow switching between multiple projects

**Prerequisites**:
- Two or more project directories
- Permission to create files in project directories

**Procedure**:

### Session 1: Project A

1. **Navigate to project A**:
   ```bash
   cd ~/projects/project-a
   ```
2. **Start Claude Code**
3. **Create project-specific file**:
   - Type: `use scaffold_write_text to create file "mympc-test.txt" with content "Project A test"`
4. **Verify creation**:
   - Type: `cat ~/projects/project-a/mympc-test.txt`
   - Expected: "Project A test"
5. **Note workspace_dir**:
   - Type: `use scaffold_where`
   - Expected: `{"workspace_dir": "/home/.../projects/project-a", ...}`
6. **Exit Claude Code**

### Session 2: Project B

7. **Navigate to project B**:
   ```bash
   cd ~/projects/project-b
   ```
8. **Start Claude Code**
9. **Create project-specific file**:
   - Type: `use scaffold_write_text to create file "mympc-test.txt" with content "Project B test"`
10. **Verify creation**:
    - Type: `cat ~/projects/project-b/mympc-test.txt`
    - Expected: "Project B test"
11. **Note workspace_dir**:
    - Type: `use scaffold_where`
    - Expected: `{"workspace_dir": "/home/.../projects/project-b", ...}`

### Verification

12. **Check both files exist in correct locations**:
    ```bash
    cat ~/projects/project-a/mympc-test.txt  # Should show "Project A test"
    cat ~/projects/project-b/mympc-test.txt  # Should show "Project B test"
    ```

### Cleanup

13. **Remove test files**:
    ```bash
    rm ~/projects/project-a/mympc-test.txt
    rm ~/projects/project-b/mympc-test.txt
    ```

**Expected Results**:
- ✅ Each session operates on its own project directory
- ✅ Files created in correct project workspace
- ✅ No interference between projects

**Pass Criteria**:
- workspace_dir correctly set for each project
- Tools operate relative to correct workspace
- Multiple projects can be worked on without manual configuration

**If Test Fails**:
- Files end up in wrong project directory → workspace_dir not updating
- Follow remediation steps from Test 3

**Status**: ⏸️ PENDING - Awaiting test execution

---

## Test 5: Tool Execution ✅

**What it tests**: Individual tool functionality works correctly

**Prerequisites**:
- mympc tools available
- Internet connectivity (for fetch_page)

**Procedure**:

### 5a: fetch_page tool

1. Type: `use fetch_page to get https://example.com`
2. Verify page content is returned
3. Check for errors

**Expected**: HTML content from example.com displayed

**Status**: ✅ PASSED (2026-02-08)

### 5b: scaffold_where tool

1. Type: `use scaffold_where`
2. Verify returns workspace_dir, module_dir, module_scope

**Expected**: JSON object with three fields

**Status**: ✅ PASSED (2026-02-08)

### 5c: scaffold_mkdir tool

1. Type: `use scaffold_mkdir to create directory "test-dir"`
2. Verify: `ls -la test-dir`
3. Cleanup: `rmdir test-dir`

**Expected**: Directory created in workspace_dir

**Status**: ⏸️ PENDING

### 5d: scaffold_write_text tool

1. Type: `use scaffold_write_text to create file "test.txt" with content "Hello World"`
2. Verify: `cat test.txt`
3. Cleanup: `rm test.txt`

**Expected**: File created with correct content

**Status**: ⏸️ PENDING

### 5e: scaffold_read_text tool

1. Create test file: `echo "test content" > read-test.txt`
2. Type: `use scaffold_read_text to read "read-test.txt"`
3. Verify content matches
4. Cleanup: `rm read-test.txt`

**Expected**: File content returned correctly

**Status**: ⏸️ PENDING

### 5f: spi_init tool

1. Navigate to empty directory or /tmp
2. Type: `use spi_init to create spi templates`
3. Verify: `ls -la spi/`
4. Check files: SPEC.md, PLAN.md, IMPLEMENT.md, TASKS.md exist

**Expected**: Template files created in ./spi/ directory

**Status**: ⏸️ PENDING

---

## Test Execution Log

### 2026-02-08: Initial Testing Session

**Tests Run**:
- ✅ Test 1: Tool Visibility
- ✅ Test 2: Current Session Workspace
- ✅ Test 5a: fetch_page tool execution

**Findings**:
- All tested functionality works correctly
- workspace_dir mechanism works for current session
- Cross-session behavior needs verification

**Next Steps**:
- Execute Test 3 (Cross-Session Workspace) to verify multi-session behavior
- Complete Test 5 (all tool subtests)
- Execute Test 4 (Multi-Project Workflow)

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
- Take screenshots if visual confirmation needed
- Save error messages verbatim

### After Testing

- Update status in Quick Status Dashboard
- Update individual test status sections
- Document findings in Test Execution Log
- If test fails, document failure mode and remediation
- Clean up all test artifacts

### Reporting Issues

If tests reveal problems:
1. Document exact failure mode
2. Include error messages and logs
3. Note environment details
4. Create issue with reproduction steps
5. Reference this test document
6. Update MCP_POSTMORTEM.md with findings
