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


class TestMcpWrapperProtocol(unittest.TestCase):
    def test_lifecycle_and_local_tool(self) -> None:
        repo_dir = Path(__file__).resolve().parents[1]
        wrapper = repo_dir / "wrapper.py"

        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)

            env = os.environ.copy()
            env["MYMPC_LOG_LEVEL"] = "error"

            p = subprocess.Popen(
                [sys.executable, str(wrapper)],
                cwd=str(cwd),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert p.stdin is not None
            assert p.stdout is not None

            # initialize
            p.stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
                    }
                ).encode("utf-8")
                + b"\n"
            )
            p.stdin.flush()
            resp = _read_json_line(p.stdout)
            self.assertEqual(resp["id"], 1)
            self.assertIn("result", resp)
            self.assertEqual(resp["result"]["protocolVersion"], "2024-11-05")

            # tools/list
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode("utf-8") + b"\n")
            p.stdin.flush()
            resp = _read_json_line(p.stdout)
            tools = {t["name"] for t in resp["result"]["tools"]}
            self.assertIn("scaffold_write_text", tools)
            self.assertIn("scaffold_read_text", tools)
            self.assertIn("scaffold_where", tools)

            # tools/call -> write
            p.stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "scaffold_write_text", "arguments": {"path": "a/b/hello.txt", "content": "hi"}},
                    }
                ).encode("utf-8")
                + b"\n"
            )
            p.stdin.flush()
            resp = _read_json_line(p.stdout)
            self.assertEqual(resp["id"], 3)
            self.assertIn("content", resp["result"])
            self.assertTrue((cwd / "a/b/hello.txt").exists())

            # tools/call -> read
            p.stdin.write(
                json.dumps(
                    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "scaffold_read_text", "arguments": {"path": "a/b/hello.txt"}}}
                ).encode("utf-8")
                + b"\n"
            )
            p.stdin.flush()
            resp = _read_json_line(p.stdout)
            content_text = resp["result"]["content"][0]["text"]
            payload = json.loads(content_text)
            self.assertEqual(payload["content"], "hi")

            # unknown tool -> tool error (isError true)
            p.stdin.write(
                json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "nope", "arguments": {}}}).encode("utf-8") + b"\n"
            )
            p.stdin.flush()
            resp = _read_json_line(p.stdout)
            self.assertTrue(resp["result"].get("isError"))

            p.stdin.close()
            p.wait(timeout=5)
            p.stdout.close()
            # Drain/close stderr to avoid ResourceWarnings.
            if p.stderr is not None:
                p.stderr.read()
                p.stderr.close()


if __name__ == "__main__":
    unittest.main()
