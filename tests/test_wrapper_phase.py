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


def _write_tool_yaml(tool_dir: Path, name: str, tools: list[dict], scope: str = "local", about: str = "") -> None:
    """Write a tool.yaml manifest for a test tool module."""
    import yaml
    manifest = {"name": name, "scope": scope, "tools": tools}
    if about:
        manifest["about"] = about
    (tool_dir / "tool.yaml").write_text(yaml.dump(manifest, default_flow_style=False), encoding="utf-8")


def _write_registry(base_dir: Path, module_paths: list[Path]) -> None:
    """Write a tools.yaml registry file."""
    import yaml
    modules = [{"path": str(p)} for p in module_paths]
    (base_dir / "tools.yaml").write_text(yaml.dump({"modules": modules}, default_flow_style=False), encoding="utf-8")


class TestWrapperTestingPhase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_dir = Path(__file__).resolve().parents[1]
        self.wrapper = self.repo_dir / "mcpp.py"

    def _start(self, *, cwd: Path, base_dir: Path) -> subprocess.Popen:
        """Start mcpp with base_dir pointing to tools.yaml location."""
        env = os.environ.copy()
        env["MCPP_LOG_LEVEL"] = "error"
        env["MCPP_BASE_DIR"] = str(base_dir)
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
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            ws = base_dir / "ws"
            ws.mkdir()

            okdir = base_dir / "tools" / "ok"
            okdir.mkdir(parents=True)
            _write_tool_yaml(okdir, "ok", [
                {"name": "ok_ping", "description": "ping", "inputSchema": {"type": "object", "properties": {}}}
            ])
            (okdir / "mcpptool.py").write_text(
                "\n".join([
                    "def execute(tool_name, arguments, context=None):",
                    "    return {'success': True, 'result': {'ok': True, 'workspace_dir': (context or {}).get('workspace_dir')}}",
                    "",
                ]),
                encoding="utf-8",
            )
            _write_registry(base_dir, [okdir])

            p = self._start(cwd=ws, base_dir=base_dir)
            assert p.stdin is not None and p.stdout is not None

            _write_req(p.stdin, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
            })
            r = _read_json_line(p.stdout)
            self.assertEqual(r["id"], 1)

            # Notification: ignored.
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

            p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "exit", "params": {}}).encode("utf-8") + b"\n")
            p.stdin.flush()
            p.stdin.close()

            p.wait(timeout=5)
            _drain_and_close(p)

    def test_module_discovery_skips_bad_modules(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            ws = base_dir / "ws"
            ws.mkdir()

            # Good module.
            gooddir = base_dir / "tools" / "good"
            gooddir.mkdir(parents=True)
            _write_tool_yaml(gooddir, "good", [
                {"name": "good_tool", "description": "ok", "inputSchema": {"type": "object", "properties": {}}}
            ])
            (gooddir / "mcpptool.py").write_text(
                "def execute(tool_name, arguments, context=None):\n    return {'success': True, 'result': 'ok'}\n",
                encoding="utf-8",
            )

            # Package module with relative import.
            pkg = base_dir / "tools" / "pkgmod"
            pkg.mkdir(parents=True)
            _write_tool_yaml(pkg, "pkgmod", [
                {"name": "pkgmod_value", "description": "value", "inputSchema": {"type": "object", "properties": {}}}
            ])
            (pkg / "helper.py").write_text("VALUE = 123\n", encoding="utf-8")
            (pkg / "mcpptool.py").write_text(
                "\n".join([
                    "from __future__ import annotations",
                    "from .helper import VALUE",
                    "def execute(tool_name, arguments, context=None):",
                    "    return {'success': True, 'result': {'value': VALUE, 'module_dir': (context or {}).get('module_dir')}}",
                    "",
                ]),
                encoding="utf-8",
            )

            # No tool.yaml: registered but skipped with warning.
            no_yaml = base_dir / "tools" / "no_yaml"
            no_yaml.mkdir(parents=True)
            (no_yaml / "mcpptool.py").write_text(
                "def execute(tool_name, arguments, context=None):\n    return {'success': True, 'result': 'nope'}\n",
                encoding="utf-8",
            )

            # tool.yaml but no mcpptool.py: skipped.
            no_main = base_dir / "tools" / "no_main"
            no_main.mkdir(parents=True)
            _write_tool_yaml(no_main, "no_main", [
                {"name": "no_main_tool", "description": "missing", "inputSchema": {"type": "object", "properties": {}}}
            ])

            # Invalid tool.yaml.
            bad_yaml = base_dir / "tools" / "bad_yaml"
            bad_yaml.mkdir(parents=True)
            (bad_yaml / "tool.yaml").write_text("name: bad\n", encoding="utf-8")
            (bad_yaml / "mcpptool.py").write_text(
                "def execute(tool_name, arguments, context=None):\n    return {'success': True, 'result': 'nope'}\n",
                encoding="utf-8",
            )

            # initialize() failure should not prevent tool from loading.
            initfail = base_dir / "tools" / "initfail"
            initfail.mkdir(parents=True)
            _write_tool_yaml(initfail, "initfail", [
                {"name": "initfail_tool", "description": "ok", "inputSchema": {"type": "object", "properties": {}}}
            ])
            (initfail / "mcpptool.py").write_text(
                "\n".join([
                    "def initialize():",
                    "    return {'success': False, 'message': 'nope'}",
                    "def execute(tool_name, arguments, context=None):",
                    "    return {'success': True, 'result': 'ok'}",
                    "",
                ]),
                encoding="utf-8",
            )

            # Register all (including bad ones — they should be skipped gracefully).
            _write_registry(base_dir, [gooddir, pkg, no_yaml, no_main, bad_yaml, initfail])

            p = self._start(cwd=ws, base_dir=base_dir)
            assert p.stdin is not None and p.stdout is not None

            try:
                _write_req(p.stdin, {
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
                })
                _read_json_line(p.stdout)

                _write_req(p.stdin, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                r = _read_json_line(p.stdout)
                tool_names = {t["name"] for t in r["result"]["tools"]}
                self.assertIn("good_tool", tool_names)
                self.assertIn("pkgmod_value", tool_names)
                self.assertIn("initfail_tool", tool_names)
                self.assertNotIn("no_yaml_tool", tool_names)
                self.assertNotIn("no_main_tool", tool_names)
                self.assertNotIn("bad_yaml_tool", tool_names)

                # Call package module and confirm module_dir.
                _write_req(p.stdin, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "pkgmod_value", "arguments": {}}})
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
            base_dir = Path(td)

            a = base_dir / "tools" / "a"
            a.mkdir(parents=True)
            _write_tool_yaml(a, "a", [
                {"name": "dup", "description": "x", "inputSchema": {"type": "object", "properties": {}}}
            ])
            (a / "mcpptool.py").write_text(
                "def execute(tool_name, arguments, context=None):\n    return {'success': True, 'result': 'a'}\n",
                encoding="utf-8",
            )
            b = base_dir / "tools" / "b"
            b.mkdir(parents=True)
            _write_tool_yaml(b, "b", [
                {"name": "dup", "description": "y", "inputSchema": {"type": "object", "properties": {}}}
            ])
            (b / "mcpptool.py").write_text(
                "def execute(tool_name, arguments, context=None):\n    return {'success': True, 'result': 'b'}\n",
                encoding="utf-8",
            )
            _write_registry(base_dir, [a, b])

            p = self._start(cwd=base_dir, base_dir=base_dir)
            assert p.stdin is not None
            p.stdin.close()
            p.wait(timeout=5)
            self.assertNotEqual(p.returncode, 0)
            _drain_and_close(p)

    def test_workspace_dir_stable_even_if_tool_chdirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            ws = base_dir / "ws"
            ws.mkdir()

            chdir = base_dir / "tools" / "chdir"
            chdir.mkdir(parents=True)
            _write_tool_yaml(chdir, "chdir", [
                {"name": "do_chdir", "description": "chdir", "inputSchema": {"type": "object", "properties": {}}},
                {"name": "report", "description": "report", "inputSchema": {"type": "object", "properties": {}}},
            ])
            (chdir / "mcpptool.py").write_text(
                "\n".join([
                    "import os",
                    "def execute(tool_name, arguments, context=None):",
                    "    if tool_name == 'do_chdir':",
                    "        os.chdir('/')",
                    "        return {'success': True, 'result': {'cwd': os.getcwd(), 'workspace_dir': (context or {}).get('workspace_dir')}}",
                    "    if tool_name == 'report':",
                    "        return {'success': True, 'result': {'cwd': os.getcwd(), 'workspace_dir': (context or {}).get('workspace_dir')}}",
                    "    return {'success': False, 'error': 'nope'}",
                    "",
                ]),
                encoding="utf-8",
            )
            _write_registry(base_dir, [chdir])

            p = self._start(cwd=ws, base_dir=base_dir)
            assert p.stdin is not None and p.stdout is not None

            _write_req(p.stdin, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
            })
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

    def test_display_key_produces_audience_annotations(self) -> None:
        """When a tool returns a display key, the wrapper emits two content items with audience annotations."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            ws = base_dir / "ws"
            ws.mkdir()

            dmod = base_dir / "tools" / "disp"
            dmod.mkdir(parents=True)
            _write_tool_yaml(dmod, "disp", [
                {"name": "disp_with", "description": "returns display", "inputSchema": {"type": "object", "properties": {}}},
                {"name": "disp_without", "description": "no display", "inputSchema": {"type": "object", "properties": {}}},
            ])
            (dmod / "mcpptool.py").write_text(
                "\n".join([
                    "def execute(tool_name, arguments, context=None):",
                    "    if tool_name == 'disp_with':",
                    "        return {'success': True, 'result': {'count': 2}, 'display': '**Items**: 2'}",
                    "    return {'success': True, 'result': {'count': 0}}",
                    "",
                ]),
                encoding="utf-8",
            )
            _write_registry(base_dir, [dmod])

            p = self._start(cwd=ws, base_dir=base_dir)
            assert p.stdin is not None and p.stdout is not None

            _write_req(p.stdin, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
            })
            _read_json_line(p.stdout)

            _write_req(p.stdin, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "disp_with", "arguments": {}}})
            r = _read_json_line(p.stdout)
            content = r["result"]["content"]
            self.assertEqual(len(content), 2)
            self.assertEqual(content[0]["text"], "**Items**: 2")
            self.assertEqual(content[0]["annotations"]["audience"], ["user"])
            data = json.loads(content[1]["text"])
            self.assertEqual(data["count"], 2)
            self.assertEqual(content[1]["annotations"]["audience"], ["assistant"])

            _write_req(p.stdin, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "disp_without", "arguments": {}}})
            r = _read_json_line(p.stdout)
            content = r["result"]["content"]
            self.assertEqual(len(content), 1)
            self.assertNotIn("annotations", content[0])

            p.stdin.close()
            p.wait(timeout=5)
            _drain_and_close(p)

    def test_lazy_loading_broken_module(self) -> None:
        """A tool with valid tool.yaml but broken mcpptool.py should be listed but fail on call."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            ws = base_dir / "ws"
            ws.mkdir()

            broken = base_dir / "tools" / "broken"
            broken.mkdir(parents=True)
            _write_tool_yaml(broken, "broken", [
                {"name": "broken_tool", "description": "will fail", "inputSchema": {"type": "object", "properties": {}}}
            ])
            (broken / "mcpptool.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
            _write_registry(base_dir, [broken])

            p = self._start(cwd=ws, base_dir=base_dir)
            assert p.stdin is not None and p.stdout is not None

            _write_req(p.stdin, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
            })
            _read_json_line(p.stdout)

            _write_req(p.stdin, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            r = _read_json_line(p.stdout)
            tool_names = {t["name"] for t in r["result"]["tools"]}
            self.assertIn("broken_tool", tool_names)

            _write_req(p.stdin, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "broken_tool", "arguments": {}}})
            r = _read_json_line(p.stdout)
            self.assertTrue(r["result"].get("isError"))
            self.assertIn("boom", r["result"]["content"][0]["text"])

            p.stdin.close()
            p.wait(timeout=5)
            _drain_and_close(p)

    def test_external_module_path(self) -> None:
        """Modules at absolute paths outside the tools/ directory should work."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td) / "mcpp"
            base_dir.mkdir()
            ws = base_dir / "ws"
            ws.mkdir()

            # External module in a completely separate directory.
            external = Path(td) / "external_tools" / "my_tool"
            external.mkdir(parents=True)
            _write_tool_yaml(external, "my_tool", [
                {"name": "my_ping", "description": "external ping", "inputSchema": {"type": "object", "properties": {}}}
            ])
            (external / "mcpptool.py").write_text(
                "def execute(tool_name, arguments, context=None):\n    return {'success': True, 'result': 'pong'}\n",
                encoding="utf-8",
            )

            # Register with absolute path.
            _write_registry(base_dir, [external])

            p = self._start(cwd=ws, base_dir=base_dir)
            assert p.stdin is not None and p.stdout is not None

            _write_req(p.stdin, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
            })
            _read_json_line(p.stdout)

            _write_req(p.stdin, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            r = _read_json_line(p.stdout)
            tool_names = {t["name"] for t in r["result"]["tools"]}
            self.assertIn("my_ping", tool_names)

            _write_req(p.stdin, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "my_ping", "arguments": {}}})
            r = _read_json_line(p.stdout)
            self.assertFalse(r["result"].get("isError"))
            self.assertIn("pong", r["result"]["content"][0]["text"])

            p.stdin.close()
            p.wait(timeout=5)
            _drain_and_close(p)


if __name__ == "__main__":
    unittest.main()
