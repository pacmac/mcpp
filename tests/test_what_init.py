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


class TestSpiInit(unittest.TestCase):
    def test_what_add_creates_templates(self) -> None:
        repo_dir = Path(__file__).resolve().parents[1]
        wrapper = repo_dir / "wrapper.py"

        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            ws.mkdir()

            env = os.environ.copy()
            env["MYMPC_LOG_LEVEL"] = "error"
            # Use real repo tools/ so what templates are present.
            env["MYMPC_MODULES_PATH"] = str(repo_dir / "tools")

            p = subprocess.Popen(
                [sys.executable, str(wrapper)],
                cwd=str(ws),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
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

            _write_req(p.stdin, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "what_add", "arguments": {"name": "test-plan"}}})
            r = _read_json_line(p.stdout)
            payload = json.loads(r["result"]["content"][0]["text"])
            self.assertTrue((ws / "what" / "test-plan" / "WHAT.md").exists())
            self.assertTrue((ws / "what" / "test-plan" / "HOW.md").exists())
            self.assertTrue((ws / "what" / "test-plan" / "ACTIONS.md").exists())
            self.assertTrue((ws / "what" / "test-plan" / "TASKS.md").exists())
            self.assertIn("written", payload)

            p.stdin.close()
            p.wait(timeout=5)
            if p.stdout is not None:
                p.stdout.read()
                p.stdout.close()
            if p.stderr is not None:
                p.stderr.read()
                p.stderr.close()


if __name__ == "__main__":
    unittest.main()

