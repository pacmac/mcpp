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

def _drain_and_close(p: subprocess.Popen) -> None:
    if p.stdout is not None:
        try:
            p.stdout.read()
        except Exception:
            pass
        try:
            p.stdout.close()
        except Exception:
            pass
    if p.stderr is not None:
        try:
            p.stderr.read()
        except Exception:
            pass
        try:
            p.stderr.close()
        except Exception:
            pass


class TestWrapperTestingPhase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_dir = Path(__file__).resolve().parents[1]
        self.wrapper = self.repo_dir / "mcpp.py"

    def _start(self, *, cwd: Path, tools_dir: Path) -> subprocess.Popen:
        env = os.environ.copy()
        env["MCPP_LOG_LEVEL"] = "error"
        env["MCPP_MODULES_PATH"] = str(tools_dir)
        return subprocess.Popen(
            [sys.executable, str(self.wrapper)],
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_protocol_errors(self) -> None:
        # Validate JSON-RPC errors and method-not-found.
        from mcpp import handle_message

        tools_list: list[dict] = []
        tools_by_name: dict = {}
        ws = "/tmp/ws"
        timeout = 1

        resp = handle_message({"jsonrpc": "2.0", "id": 1, "method": 123}, tools_list, tools_by_name, ws, timeout)
        self.assertEqual(resp["error"]["code"], -32600)

        resp = handle_message({"jsonrpc": "2.0", "id": 2, "method": "nope", "params": {}}, tools_list, tools_by_name, ws, timeout)
        self.assertEqual(resp["error"]["code"], -32601)

        resp = handle_message({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": "bad"}, tools_list, tools_by_name, ws, timeout)
        self.assertEqual(resp["error"]["code"], -32602)

    def test_shutdown_exit_lifecycle(self) -> None:
        # initialize -> notifications/initialized (ignored) -> tools/list -> tools/call -> shutdown -> exit
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            ws.mkdir()

            tools_dir = Path(td) / "tools"
            tools_dir.mkdir()
            (tools_dir / "__init__.py").write_text("", encoding="utf-8")

            okdir = tools_dir / "ok"
            okdir.mkdir()
            (okdir / "main.py").write_text(
                "\n".join(
                    [
                        'MODULE_NAME="ok"',
                        'MODULE_SCOPE="local"',
                        "TOOLS=[{"
                        '"name":"ok_ping",'
                        '"description":"ping",'
                        '"inputSchema":{"type":"object","properties":{}}'
                        "}]",
                        "def execute(tool_name, arguments, context=None):",
                        "    return {'success': True, 'result': {'ok': True, 'workspace_dir': (context or {}).get('workspace_dir')}}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            p = self._start(cwd=ws, tools_dir=tools_dir)
            assert p.stdin is not None and p.stdout is not None

            _write_req(
                p.stdin,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
                },
            )
            r = _read_json_line(p.stdout)
            self.assertEqual(r["id"], 1)

            # Notification: ignored (no response).
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}).encode("utf-8") + b"\n")
            p.stdin.flush()

            _write_req(p.stdin, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            r = _read_json_line(p.stdout)
            tools = {t["name"] for t in r["result"]["tools"]}
            self.assertIn("ok_ping", tools)

            _write_req(p.stdin, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ok_ping", "arguments": {}}})
            r = _read_json_line(p.stdout)
            payload = json.loads(r["result"]["content"][0]["text"])
            self.assertEqual(payload["workspace_dir"], str(ws.resolve()))

            _write_req(p.stdin, {"jsonrpc": "2.0", "id": 4, "method": "shutdown", "params": {}})
            r = _read_json_line(p.stdout)
            self.assertEqual(r["id"], 4)
            self.assertIn("result", r)

            # exit notification
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "exit", "params": {}}).encode("utf-8") + b"\n")
            p.stdin.flush()
            p.stdin.close()

            p.wait(timeout=5)
            _drain_and_close(p)

    def test_module_discovery_skips_bad_modules(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            ws.mkdir()
            tools_dir = Path(td) / "tools"
            tools_dir.mkdir()
            (tools_dir / "__init__.py").write_text("", encoding="utf-8")

            # Good module (directory form).
            gooddir = tools_dir / "good"
            gooddir.mkdir()
            (gooddir / "main.py").write_text(
                "\n".join(
                    [
                        'MODULE_NAME="good"',
                        "TOOLS=[{"
                        '"name":"good_tool",'
                        '"description":"ok",'
                        '"inputSchema":{"type":"object","properties":{}}'
                        "}]",
                        "def execute(tool_name, arguments, context=None):",
                        "    return {'success': True, 'result': 'ok'}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            # Directory module with relative import.
            pkg = tools_dir / "pkgmod"
            pkg.mkdir()
            (pkg / "helper.py").write_text("VALUE = 123\n", encoding="utf-8")
            (pkg / "main.py").write_text(
                "\n".join(
                    [
                        "from __future__ import annotations",
                        "from .helper import VALUE",
                        'MODULE_NAME="pkgmod"',
                        "TOOLS=[{"
                        '"name":"pkgmod_value",'
                        '"description":"value",'
                        '"inputSchema":{"type":"object","properties":{}}'
                        "}]",
                        "def execute(tool_name, arguments, context=None):",
                        "    return {'success': True, 'result': {'value': VALUE, 'module_dir': (context or {}).get('module_dir')}}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            # Wrapper ignores underscore-prefixed modules.
            (tools_dir / "_ignored.py").write_text(
                "\n".join(
                    [
                        'MODULE_NAME="ignored"',
                        "TOOLS=[{"
                        '"name":"ignored_tool",'
                        '"description":"should not load",'
                        '"inputSchema":{"type":"object","properties":{}}'
                        "}]",
                        "def execute(tool_name, arguments, context=None):",
                        "    return {'success': True, 'result': 'nope'}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            ignored_dir = tools_dir / "_ignored_dir"
            ignored_dir.mkdir()
            (ignored_dir / "main.py").write_text(
                "\n".join(
                    [
                        'MODULE_NAME="ignored_dir"',
                        "TOOLS=[{"
                        '"name":"ignored_dir_tool",'
                        '"description":"should not load",'
                        '"inputSchema":{"type":"object","properties":{}}'
                        "}]",
                        "def execute(tool_name, arguments, context=None):",
                        "    return {'success': True, 'result': 'nope'}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            # Import error module.
            badimp = tools_dir / "bad_import"
            badimp.mkdir()
            (badimp / "main.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")

            # Missing exports.
            missing = tools_dir / "missing"
            missing.mkdir()
            (missing / "main.py").write_text("MODULE_NAME='x'\n", encoding="utf-8")

            # initialize() failure should not remove module.
            initfail = tools_dir / "initfail"
            initfail.mkdir()
            (initfail / "main.py").write_text(
                "\n".join(
                    [
                        'MODULE_NAME="initfail"',
                        "TOOLS=[{"
                        '"name":"initfail_tool",'
                        '"description":"ok",'
                        '"inputSchema":{"type":"object","properties":{}}'
                        "}]",
                        "def initialize():",
                        "    return {'success': False, 'message': 'nope'}",
                        "def execute(tool_name, arguments, context=None):",
                        "    return {'success': True, 'result': 'ok'}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            p = self._start(cwd=ws, tools_dir=tools_dir)
            assert p.stdin is not None and p.stdout is not None

            try:
                _write_req(
                    p.stdin,
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
                    },
                )
                _read_json_line(p.stdout)

                _write_req(p.stdin, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                r = _read_json_line(p.stdout)
                tool_names = {t["name"] for t in r["result"]["tools"]}
                self.assertIn("good_tool", tool_names)
                self.assertIn("pkgmod_value", tool_names)
                self.assertIn("initfail_tool", tool_names)
                self.assertNotIn("missing_tool", tool_names)
                self.assertNotIn("ignored_tool", tool_names)
                self.assertNotIn("ignored_dir_tool", tool_names)

                # Call directory tool and confirm module_dir points at tools/pkgmod
                _write_req(
                    p.stdin,
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "pkgmod_value", "arguments": {}}},
                )
                r = _read_json_line(p.stdout)
                payload = json.loads(r["result"]["content"][0]["text"])
                self.assertEqual(payload["value"], 123)
                self.assertTrue(str(payload["module_dir"]).endswith("/tools/pkgmod"))
            finally:
                try:
                    if p.stdin is not None:
                        p.stdin.close()
                except Exception:
                    pass
                try:
                    p.wait(timeout=5)
                except Exception:
                    try:
                        p.terminate()
                    except Exception:
                        pass
                _drain_and_close(p)

    def test_duplicate_tool_name_fails_startup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            ws.mkdir()
            tools_dir = Path(td) / "tools"
            tools_dir.mkdir()
            (tools_dir / "__init__.py").write_text("", encoding="utf-8")

            a = tools_dir / "a"
            a.mkdir()
            (a / "main.py").write_text(
                "\n".join(
                    [
                        'MODULE_NAME="a"',
                        "TOOLS=[{"
                        '"name":"dup",'
                        '"description":"x",'
                        '"inputSchema":{"type":"object","properties":{}}'
                        "}]",
                        "def execute(tool_name, arguments, context=None):",
                        "    return {'success': True, 'result': 'a'}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            b = tools_dir / "b"
            b.mkdir()
            (b / "main.py").write_text(
                "\n".join(
                    [
                        'MODULE_NAME="b"',
                        "TOOLS=[{"
                        '"name":"dup",'
                        '"description":"y",'
                        '"inputSchema":{"type":"object","properties":{}}'
                        "}]",
                        "def execute(tool_name, arguments, context=None):",
                        "    return {'success': True, 'result': 'b'}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            p = self._start(cwd=ws, tools_dir=tools_dir)
            assert p.stdin is not None
            p.stdin.close()
            p.wait(timeout=5)
            self.assertNotEqual(p.returncode, 0)
            _drain_and_close(p)

    def test_workspace_dir_stable_even_if_tool_chdirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            ws.mkdir()
            tools_dir = Path(td) / "tools"
            tools_dir.mkdir()
            (tools_dir / "__init__.py").write_text("", encoding="utf-8")

            chdir = tools_dir / "chdir"
            chdir.mkdir()
            (chdir / "main.py").write_text(
                "\n".join(
                    [
                        "import os",
                        'MODULE_NAME="chdir"',
                        "TOOLS=["
                        "{"
                        '"name":"do_chdir",'
                        '"description":"chdir",'
                        '"inputSchema":{"type":"object","properties":{}}'
                        "},"
                        "{"
                        '"name":"report",'
                        '"description":"report",'
                        '"inputSchema":{"type":"object","properties":{}}'
                        "}"
                        "]",
                        "def execute(tool_name, arguments, context=None):",
                        "    if tool_name == 'do_chdir':",
                        "        os.chdir('/')",
                        "        return {'success': True, 'result': {'cwd': os.getcwd(), 'workspace_dir': (context or {}).get('workspace_dir')}}",
                        "    if tool_name == 'report':",
                        "        return {'success': True, 'result': {'cwd': os.getcwd(), 'workspace_dir': (context or {}).get('workspace_dir')}}",
                        "    return {'success': False, 'error': 'nope'}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            p = self._start(cwd=ws, tools_dir=tools_dir)
            assert p.stdin is not None and p.stdout is not None

            _write_req(
                p.stdin,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
                },
            )
            _read_json_line(p.stdout)

            _write_req(p.stdin, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "do_chdir", "arguments": {}}})
            r = _read_json_line(p.stdout)
            a = json.loads(r["result"]["content"][0]["text"])
            self.assertEqual(a["workspace_dir"], str(ws.resolve()))

            _write_req(p.stdin, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "report", "arguments": {}}})
            r = _read_json_line(p.stdout)
            b = json.loads(r["result"]["content"][0]["text"])
            self.assertEqual(b["workspace_dir"], str(ws.resolve()))

            p.stdin.close()
            p.wait(timeout=5)
            _drain_and_close(p)


if __name__ == "__main__":
    unittest.main()
