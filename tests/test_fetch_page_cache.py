import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_fetch_module() -> object:
    p = Path(__file__).resolve().parents[1] / "tools" / "fetch_page" / "main.py"
    spec = importlib.util.spec_from_file_location("test_fetch_page_main", str(p))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class _FakeResp:
    def __init__(self, body: bytes, content_type: str = "text/plain"):
        self._body = body
        self.headers = {"content-type": content_type}

    def read(self, n: int) -> bytes:
        return self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestFetchPageCache(unittest.TestCase):
    def test_caches_and_reuses_within_ttl(self) -> None:
        mod = _load_fetch_module()

        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "fetch_page"
            module_dir.mkdir()

            # Seed config.
            (module_dir / "cache.yaml").write_text("ttl_seconds: 3600\nentries:\n", encoding="utf-8")

            url = "https://unit.test/page"

            # First call should hit network and write cache.
            def urlopen_ok(req, timeout=0):
                return _FakeResp(b"hello world", "text/plain")

            mod.urllib.request.urlopen = urlopen_ok  # type: ignore[attr-defined]

            r1 = mod.execute("fetch_page", {"url": url, "max_chars": 20000}, {"module_dir": str(module_dir)})
            self.assertTrue(r1["success"])
            payload1 = r1["result"]
            self.assertFalse(payload1["cached"])
            self.assertIn("hello world", payload1["text"])

            # Second call should be cached; fail test if it tries network.
            def urlopen_fail(req, timeout=0):
                raise AssertionError("network called despite valid cache")

            mod.urllib.request.urlopen = urlopen_fail  # type: ignore[attr-defined]

            r2 = mod.execute("fetch_page", {"url": url, "max_chars": 20000}, {"module_dir": str(module_dir)})
            self.assertTrue(r2["success"])
            payload2 = r2["result"]
            self.assertTrue(payload2["cached"])
            self.assertIn("hello world", payload2["text"])

            # Ensure cache.yaml mentions the URL and downloads file exists.
            cache_text = (module_dir / "cache.yaml").read_text(encoding="utf-8")
            self.assertIn(json.dumps(url), cache_text)
            downloads = module_dir / "downloads"
            self.assertTrue(downloads.exists())
            self.assertTrue(any(p.suffix == ".bin" for p in downloads.iterdir()))

