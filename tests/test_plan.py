"""Tests for the plan (agent) MCP tool — task and step CRUD operations."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _read_json_line(stdout) -> dict:
    line = stdout.readline()
    if not line:
        raise RuntimeError("no response from wrapper")
    return json.loads(line.decode("utf-8"))


def _write_req(stdin, obj: dict) -> None:
    stdin.write(json.dumps(obj).encode("utf-8") + b"\n")
    stdin.flush()


def _call_tool_raw(stdin, stdout, req_id: int, name: str, arguments: dict) -> dict:
    """Send a tools/call request and return the raw MCP result (content list)."""
    _write_req(stdin, {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    resp = _read_json_line(stdout)
    assert resp["id"] == req_id, f"id mismatch: expected {req_id}, got {resp['id']}"
    return resp["result"]


def _call_tool(stdin, stdout, req_id: int, name: str, arguments: dict) -> dict:
    """Send a tools/call request and return the parsed result payload.

    Handles both single-content (no display) and dual-content (display + data)
    responses. For dual-content, parses the assistant-audience item.
    """
    result = _call_tool_raw(stdin, stdout, req_id, name, arguments)
    if result.get("isError"):
        text = result["content"][0]["text"] if result.get("content") else ""
        return {"error": text}
    content = result["content"]
    if not content:
        return {}
    # Dual-content: find the assistant-audience item (JSON data)
    if len(content) > 1:
        for item in content:
            audience = item.get("annotations", {}).get("audience", [])
            if "assistant" in audience:
                return json.loads(item["text"])
    # Single-content: parse as JSON
    return json.loads(content[0]["text"])


class TestPlanTools(unittest.TestCase):
    """End-to-end tests for plan_task_* and plan_step_* MCP tools."""

    @classmethod
    def setUpClass(cls):
        repo_dir = Path(__file__).resolve().parents[1]
        wrapper = repo_dir / "mcpp.py"

        cls._td = tempfile.TemporaryDirectory()
        cls.workspace = Path(cls._td.name) / "ws"
        cls.workspace.mkdir()

        env = os.environ.copy()
        env["MCPP_LOG_LEVEL"] = "error"
        env["MCPP_MODULES_PATH"] = str(repo_dir / "tools")

        cls.proc = subprocess.Popen(
            [sys.executable, str(wrapper)],
            cwd=str(cls.workspace),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert cls.proc.stdin is not None and cls.proc.stdout is not None

        # Initialize MCP
        _write_req(cls.proc.stdin, {
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        })
        resp = _read_json_line(cls.proc.stdout)
        assert resp["id"] == 0

        cls._req_id = 0

    @classmethod
    def tearDownClass(cls):
        if cls.proc.stdin:
            cls.proc.stdin.close()
        cls.proc.wait(timeout=5)
        if cls.proc.stdout:
            cls.proc.stdout.read()
            cls.proc.stdout.close()
        if cls.proc.stderr:
            cls.proc.stderr.read()
            cls.proc.stderr.close()
        cls._td.cleanup()

    def _call_raw(self, tool_name: str, arguments: dict | None = None) -> dict:
        """Return the raw MCP result with content list."""
        self.__class__._req_id += 1
        return _call_tool_raw(
            self.proc.stdin, self.proc.stdout,
            self._req_id, tool_name, arguments or {},
        )

    def _call(self, tool_name: str, arguments: dict | None = None) -> dict:
        self.__class__._req_id += 1
        return _call_tool(
            self.proc.stdin, self.proc.stdout,
            self._req_id, tool_name, arguments or {},
        )

    # ── Task tests ──

    def test_01_task_new(self):
        """Create a task with steps."""
        r = self._call("plan_task_new", {
            "name": "alpha",
            "title": "Alpha task",
            "steps": ["Step one", "Step two", "Step three"],
        })
        self.assertIn("context_id", r)
        self.assertEqual(r["context_name"], "alpha")
        tasks = r.get("tasks", [])
        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0]["title"], "Step one")
        self.assertEqual(tasks[2]["title"], "Step three")

    def test_02_task_status(self):
        """Status shows the active task."""
        r = self._call("plan_task_status")
        self.assertEqual(r["context_name"], "alpha")
        self.assertEqual(r["active_task_number"], 1)

    def test_03_task_show_active(self):
        """Show active task details."""
        r = self._call("plan_task_show")
        self.assertEqual(r["context_name"], "alpha")
        self.assertIn("tasks", r)

    def test_04_task_show_by_name(self):
        """Show task by name."""
        r = self._call("plan_task_show", {"name": "alpha"})
        self.assertEqual(r["context_name"], "alpha")

    def test_05_task_list(self):
        """List all tasks."""
        r = self._call("plan_task_list")
        tasks = r["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["name"], "alpha")

    def test_06_task_new_second(self):
        """Create a second task."""
        r = self._call("plan_task_new", {
            "name": "beta",
            "title": "Beta task",
            "steps": ["Beta step A", "Beta step B"],
        })
        self.assertEqual(r["context_name"], "beta")

    def test_07_task_list_two(self):
        """List shows both tasks."""
        r = self._call("plan_task_list")
        names = [t["name"] for t in r["tasks"]]
        self.assertIn("alpha", names)
        self.assertIn("beta", names)

    def test_08_task_switch(self):
        """Switch to alpha task."""
        r = self._call("plan_task_switch", {"name": "alpha"})
        self.assertEqual(r["context_name"], "alpha")

    def test_09_task_archive(self):
        """Archive beta task."""
        r = self._call("plan_task_archive", {"name": "beta"})
        self.assertTrue(r["success"] if "success" in r else "archived" in r)

    def test_10_task_list_no_archived(self):
        """Archived task excluded from default list."""
        r = self._call("plan_task_list")
        names = [t["name"] for t in r["tasks"]]
        self.assertIn("alpha", names)
        self.assertNotIn("beta", names)

    def test_11_task_list_show_archived(self):
        """Archived task included when show_archived=true."""
        r = self._call("plan_task_list", {"show_archived": True})
        names = [t["name"] for t in r["tasks"]]
        self.assertIn("alpha", names)
        self.assertIn("beta", names)

    def test_12_archive_active_task_refused(self):
        """Archiving the active task should fail."""
        r = self._call("plan_task_archive", {"name": "alpha"})
        self.assertIn("error", r)
        self.assertIn("active", r["error"].lower())

    # ── Step tests (on alpha task) ──

    def test_20_step_list(self):
        """List steps in active task."""
        r = self._call("plan_step_list")
        steps = r["tasks"]
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0]["title"], "Step one")

    def test_21_step_show(self):
        """Show a specific step."""
        r = self._call("plan_step_show", {"number": 2})
        self.assertEqual(r["title"], "Step two")

    def test_22_step_switch(self):
        """Switch active step."""
        r = self._call("plan_step_switch", {"number": 2})
        self.assertIn("title", r)

    def test_23_step_done(self):
        """Mark step as complete."""
        r = self._call("plan_step_done", {"number": 1})
        self.assertEqual(r["status"], "complete")

    def test_24_step_show_completed(self):
        """Verify completed step status."""
        r = self._call("plan_step_show", {"number": 1})
        self.assertEqual(r["status"], "complete")

    def test_25_step_new(self):
        """Add a new step to active task."""
        r = self._call("plan_step_new", {"title": "Step four"})
        self.assertIn("title", r)

    def test_26_step_list_after_add(self):
        """List reflects added step."""
        r = self._call("plan_step_list")
        titles = [t["title"] for t in r["tasks"]]
        self.assertEqual(len(titles), 4)
        self.assertIn("Step four", titles)

    def test_27_step_delete(self):
        """Delete a step."""
        r = self._call("plan_step_delete", {"number": 4})
        # Returns updated step list
        self.assertIn("tasks", r)

    def test_28_step_list_after_delete(self):
        """Deleted step excluded from list."""
        r = self._call("plan_step_list")
        visible = [t for t in r["tasks"] if not t.get("is_deleted")]
        self.assertEqual(len(visible), 3)

    def test_29_step_notes_empty(self):
        """Reading notes on step with none returns empty list."""
        r = self._call("plan_step_notes", {"number": 2})
        notes = r.get("notes", [])
        self.assertIsInstance(notes, list)

    def test_30_step_notes_add(self):
        """Add a note to a step."""
        r = self._call("plan_step_notes", {"number": 2, "text": "This is a test note"})
        notes = r.get("notes", [])
        self.assertGreaterEqual(len(notes), 1)

    def test_31_step_notes_read(self):
        """Read notes back."""
        r = self._call("plan_step_notes", {"number": 2})
        notes = r.get("notes", [])
        self.assertEqual(len(notes), 1)
        self.assertIn("test note", notes[0].get("note", "").lower())

    def test_32_step_notes_add_second(self):
        """Add a second note."""
        r = self._call("plan_step_notes", {"number": 2, "text": "Second note"})
        notes = r.get("notes", [])
        self.assertEqual(len(notes), 2)

    # ── Task notes tests ──

    def test_33_task_notes_empty(self):
        """Reading notes on task with none returns empty list."""
        r = self._call("plan_task_notes")
        notes = r.get("notes", [])
        self.assertIsInstance(notes, list)
        self.assertEqual(len(notes), 0)

    def test_34_task_notes_add(self):
        """Add a note to the active task."""
        r = self._call("plan_task_notes", {"text": "Task-level test note"})
        notes = r.get("notes", [])
        self.assertGreaterEqual(len(notes), 1)
        self.assertIn("Task-level test note", notes[0]["note"])

    def test_35_task_notes_read(self):
        """Read task notes back."""
        r = self._call("plan_task_notes")
        notes = r.get("notes", [])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["note"], "Task-level test note")

    def test_36_task_notes_add_second(self):
        """Add a second task note."""
        r = self._call("plan_task_notes", {"text": "Second task note"})
        notes = r.get("notes", [])
        self.assertEqual(len(notes), 2)

    def test_37_task_notes_by_name(self):
        """Read task notes by task name."""
        r = self._call("plan_task_notes", {"name": "alpha"})
        notes = r.get("notes", [])
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0]["note"], "Task-level test note")
        self.assertEqual(notes[1]["note"], "Second task note")

    # ── Display annotation tests ──

    def test_50_task_show_has_display(self):
        """task_show returns dual content with audience annotations."""
        raw = self._call_raw("plan_task_show")
        content = raw["content"]
        self.assertEqual(len(content), 2)
        # First item: user-facing display text
        self.assertEqual(content[0]["annotations"]["audience"], ["user"])
        self.assertIn("alpha", content[0]["text"])
        # Second item: assistant-facing JSON
        self.assertEqual(content[1]["annotations"]["audience"], ["assistant"])
        data = json.loads(content[1]["text"])
        self.assertIn("context_name", data)

    def test_51_task_status_has_display(self):
        """task_status returns dual content with audience annotations."""
        raw = self._call_raw("plan_task_status")
        content = raw["content"]
        self.assertEqual(len(content), 2)
        self.assertEqual(content[0]["annotations"]["audience"], ["user"])
        self.assertEqual(content[1]["annotations"]["audience"], ["assistant"])

    def test_52_task_list_has_display(self):
        """task_list returns dual content with audience annotations."""
        raw = self._call_raw("plan_task_list")
        content = raw["content"]
        self.assertEqual(len(content), 2)
        self.assertIn("alpha", content[0]["text"])

    def test_53_step_list_has_display(self):
        """step_list returns dual content with audience annotations."""
        raw = self._call_raw("plan_step_list")
        content = raw["content"]
        self.assertEqual(len(content), 2)
        self.assertIn("Step one", content[0]["text"])

    def test_54_step_show_has_display(self):
        """step_show returns dual content with audience annotations."""
        raw = self._call_raw("plan_step_show", {"number": 2})
        content = raw["content"]
        self.assertEqual(len(content), 2)
        self.assertIn("Step two", content[0]["text"])

    def test_55_step_notes_has_display(self):
        """step_notes returns dual content with audience annotations."""
        raw = self._call_raw("plan_step_notes", {"number": 2})
        content = raw["content"]
        self.assertEqual(len(content), 2)
        self.assertIn("note", content[0]["text"].lower())

    def test_56_task_notes_has_display(self):
        """task_notes returns dual content with audience annotations."""
        raw = self._call_raw("plan_task_notes")
        content = raw["content"]
        self.assertEqual(len(content), 2)
        self.assertIn("Task-level test note", content[0]["text"])

    # ── Project tests ──

    def test_70_project_show_auto_populated(self):
        """project_show returns auto-populated project from init."""
        r = self._call("plan_project_show")
        self.assertIn("project_name", r)
        self.assertIn("absolute_path", r)
        # Name should be the workspace directory basename
        self.assertEqual(r["project_name"], "ws")

    def test_71_project_set_name_and_description(self):
        """project_set updates name and description."""
        r = self._call("plan_project_set", {
            "name": "test-project",
            "description": "A test project for unit tests",
        })
        self.assertEqual(r["project_name"], "test-project")
        self.assertEqual(r["description_md"], "A test project for unit tests")

    def test_72_project_show_after_set(self):
        """project_show reflects updates from project_set."""
        r = self._call("plan_project_show")
        self.assertEqual(r["project_name"], "test-project")
        self.assertEqual(r["description_md"], "A test project for unit tests")

    def test_73_project_set_partial_update(self):
        """project_set with only name preserves description."""
        r = self._call("plan_project_set", {"name": "renamed-project"})
        self.assertEqual(r["project_name"], "renamed-project")
        self.assertEqual(r["description_md"], "A test project for unit tests")

    def test_74_project_show_has_display(self):
        """project_show returns dual content with audience annotations."""
        raw = self._call_raw("plan_project_show")
        content = raw["content"]
        self.assertEqual(len(content), 2)
        self.assertIn("renamed-project", content[0]["text"])

    def test_75_project_name_in_responses(self):
        """All tool responses include project_name field."""
        r = self._call("plan_task_status")
        self.assertIn("project_name", r)
        self.assertEqual(r["project_name"], "renamed-project")

    # ── Edge cases ──

    def test_60_step_done_already_complete(self):
        """Completing an already-complete step should not error."""
        r = self._call("plan_step_done", {"number": 1})
        self.assertEqual(r["status"], "complete")

    def test_61_task_status_reflects_progress(self):
        """Status shows correct counts after operations."""
        r = self._call("plan_task_status")
        self.assertEqual(r["context_name"], "alpha")
        self.assertGreaterEqual(r["completed_count"], 1)

    # ── User tests ──

    def test_80_tasks_have_user(self):
        """Tasks created via MCP are assigned to the OS user."""
        # Verify by checking the DB directly
        import sqlite3
        db_path = self.workspace / "plan.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT c.user_id, u.name FROM contexts c "
            "JOIN users u ON u.id = c.user_id "
            "WHERE c.name = 'alpha'"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertIsNotNone(row["user_id"])
        self.assertEqual(row["name"], os.environ.get("USER", "root"))

    def test_81_user_state_tracks_active(self):
        """user_state tracks the active context for the OS user."""
        import sqlite3
        db_path = self.workspace / "plan.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT us.active_context_id, u.name FROM user_state us "
            "JOIN users u ON u.id = us.user_id"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertIsNotNone(row["active_context_id"])

    def test_82_task_list_default_filters_by_user(self):
        """Default task list only shows current user's tasks."""
        r = self._call("plan_task_list")
        tasks = r["tasks"]
        # All tasks should belong to current user (no 'user' key in non-all mode)
        for t in tasks:
            self.assertNotIn("user", t)

    def test_83_task_list_show_all_includes_user(self):
        """task_list with show_all=true includes user field."""
        r = self._call("plan_task_list", {"show_all": True, "show_archived": True})
        tasks = r["tasks"]
        self.assertGreater(len(tasks), 0)
        for t in tasks:
            self.assertIn("user", t)
            self.assertEqual(t["user"], os.environ.get("USER", "root"))

    def test_84_task_list_show_all_display_grouped(self):
        """task_list show_all display text is grouped by user."""
        raw = self._call_raw("plan_task_list", {"show_all": True, "show_archived": True})
        content = raw["content"]
        self.assertEqual(len(content), 2)
        display = content[0]["text"]
        self.assertIn("all users", display.lower())
        user = os.environ.get("USER", "root")
        self.assertIn(f"**{user}**", display)

    def test_85_multi_user_isolation(self):
        """Tasks created by different users are isolated in default list."""
        # Manually insert a task for a fake user directly in DB
        import sqlite3
        db_path = self.workspace / "plan.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        now = "2026-01-01T00:00:00+00:00"
        conn.execute(
            "INSERT INTO users (name, created_at) VALUES (?, ?)",
            ("fake-other-user", now),
        )
        fake_uid = conn.execute(
            "SELECT id FROM users WHERE name = 'fake-other-user'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO contexts (name, status, description_md, user_id, created_at, updated_at) "
            "VALUES (?, 'active', ?, ?, ?, ?)",
            ("other-task", "Task owned by another user", fake_uid, now, now),
        )
        conn.execute(
            "INSERT INTO context_state (context_id, status_label, last_event, updated_at) "
            "VALUES ((SELECT id FROM contexts WHERE name='other-task'), 'Created', 'Context Created', ?)",
            (now,),
        )
        conn.commit()
        conn.close()

        # Default list should NOT include other-task
        r = self._call("plan_task_list")
        names = [t["name"] for t in r["tasks"]]
        self.assertNotIn("other-task", names)

        # show_all should include it
        r = self._call("plan_task_list", {"show_all": True})
        names = [t["name"] for t in r["tasks"]]
        self.assertIn("other-task", names)

        # Verify user grouping
        other_tasks = [t for t in r["tasks"] if t["name"] == "other-task"]
        self.assertEqual(len(other_tasks), 1)
        self.assertEqual(other_tasks[0]["user"], "fake-other-user")

    # ── User alias tests ──

    def test_86_user_show(self):
        """user_show returns current OS user info."""
        r = self._call("plan_user_show")
        self.assertIn("name", r)
        self.assertEqual(r["name"], os.environ.get("USER", "root"))
        self.assertIn("display_name", r)

    def test_87_user_set_alias(self):
        """user_set sets the display name."""
        r = self._call("plan_user_set", {"alias": "TestAlias"})
        self.assertEqual(r["display_name"], "TestAlias")
        self.assertEqual(r["name"], os.environ.get("USER", "root"))

    def test_88_user_show_after_alias(self):
        """user_show reflects the alias after setting it."""
        r = self._call("plan_user_show")
        self.assertEqual(r["display_name"], "TestAlias")

    def test_89_user_alias_in_task_list_all(self):
        """show_all task list uses display_name instead of login."""
        r = self._call("plan_task_list", {"show_all": True})
        my_tasks = [t for t in r["tasks"] if t["name"] == "alpha"]
        self.assertEqual(len(my_tasks), 1)
        self.assertEqual(my_tasks[0]["user"], "TestAlias")

    def test_90_user_alias_display_grouped(self):
        """Grouped display text uses alias."""
        raw = self._call_raw("plan_task_list", {"show_all": True, "show_archived": True})
        content = raw["content"]
        display = content[0]["text"]
        self.assertIn("**TestAlias**", display)

    def test_91_user_show_has_display(self):
        """user_show returns dual content with audience annotations."""
        raw = self._call_raw("plan_user_show")
        content = raw["content"]
        self.assertEqual(len(content), 2)
        self.assertIn("TestAlias", content[0]["text"])


if __name__ == "__main__":
    unittest.main()
