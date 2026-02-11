from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

MODULE_NAME = "fetch_page"
MODULE_SCOPE = "global"
MODULE_ABOUT = "Fetches URL content with on-disk caching. Use when you need to retrieve and read web page content."

TOOLS = [
    {
        "name": "fetch_page",
        "description": "Fetch a URL (with on-disk cache under this module dir) and return the first N characters of the response body.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 1, "maximum": 200000},
            },
            "required": ["url"],
        },
    }
]


def get_info(context: dict[str, Any] | None = None) -> dict[str, Any]:
    module_dir = (context or {}).get("module_dir") or str(Path(__file__).resolve().parent)
    cache_path, _ = _cache_paths(module_dir)
    cache = _read_cache_yaml(cache_path)
    return {
        "params": {
            "url": {"values": None, "default": None},
            "max_chars": {"values": None, "default": 20000},
        },
        "cache_ttl_seconds": cache.get("ttl_seconds", 3600),
    }


def _load_user_agent(module_dir: str) -> str:
    # Optional data source stored next to the module, for "global" scope tools.
    # If not present, fall back to a hard-coded UA.
    p = Path(module_dir) / "user_agent.txt"
    try:
        s = p.read_text(encoding="utf-8").strip()
        return s or "mcpp-fetch/0.1"
    except Exception:
        return "mcpp-fetch/0.1"


def _cache_paths(module_dir: str) -> tuple[Path, Path]:
    md = Path(module_dir)
    return md / "cache.yaml", md / "downloads"


def _yaml_unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1]
    return s


def _read_cache_yaml(cache_path: Path) -> dict[str, Any]:
    # Minimal YAML reader for our own emitted format.
    # Format:
    # ttl_seconds: 3600
    # entries:
    #   - url: "..."
    #     fetched_at: 1700000000
    #     content_type: "text/html"
    #     path: "downloads/<hash>.bin"
    data: dict[str, Any] = {"ttl_seconds": 3600, "entries": []}
    if not cache_path.exists():
        return data

    try:
        lines = cache_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return data

    entries: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    in_entries = False

    def _parse_kv(part: str) -> tuple[str, Any] | None:
        if ":" not in part:
            return None
        k, v = part.split(":", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            return None
        if v.isdigit():
            return k, int(v)
        return k, _yaml_unquote(v)

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("ttl_seconds:"):
            _, v = line.split(":", 1)
            v = v.strip()
            if v.isdigit():
                data["ttl_seconds"] = int(v)
            continue
        if line == "entries:":
            in_entries = True
            continue
        if not in_entries:
            continue

        if line.startswith("- "):
            cur = {}
            entries.append(cur)
            kv = _parse_kv(line[2:].strip())
            if kv is not None:
                k, v = kv
                cur[k] = v
            continue

        if cur is None:
            continue
        kv = _parse_kv(line)
        if kv is None:
            continue
        k, v = kv
        cur[k] = v

    data["entries"] = entries
    return data


def _write_cache_yaml(cache_path: Path, data: dict[str, Any]) -> None:
    ttl = int(data.get("ttl_seconds") or 0)
    entries = data.get("entries") or []
    if not isinstance(entries, list):
        entries = []

    lines: list[str] = []
    lines.append(f"ttl_seconds: {ttl}")
    lines.append("entries:")
    for e in entries:
        if not isinstance(e, dict):
            continue
        url = e.get("url")
        if not isinstance(url, str) or not url:
            continue
        lines.append(f"  - url: {json.dumps(url, ensure_ascii=True)}")
        for k in ("fetched_at", "content_type", "path", "size"):
            v = e.get(k)
            if v is None:
                continue
            if isinstance(v, int):
                lines.append(f"    {k}: {v}")
            else:
                lines.append(f"    {k}: {json.dumps(str(v), ensure_ascii=True)}")

    cache_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8", errors="strict")).hexdigest()


def _find_entry(entries: list[dict[str, Any]], url: str) -> dict[str, Any] | None:
    for e in entries:
        if isinstance(e, dict) and e.get("url") == url:
            return e
    return None


def execute(tool_name: str, arguments: dict[str, Any], context: dict | None = None) -> dict[str, Any]:
    try:
        if tool_name != "fetch_page":
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        url = str(arguments["url"])
        max_chars = int(arguments.get("max_chars", 20000))
        module_dir = (context or {}).get("module_dir") or str(Path(__file__).resolve().parent)

        cache_path, downloads_dir = _cache_paths(module_dir)
        downloads_dir.mkdir(parents=True, exist_ok=True)

        cache = _read_cache_yaml(cache_path)
        ttl_seconds = int(cache.get("ttl_seconds") or 0)
        entries = cache.get("entries") or []
        if not isinstance(entries, list):
            entries = []

        now = int(time.time())
        ent = _find_entry(entries, url)
        if ent and ttl_seconds > 0:
            fetched_at = ent.get("fetched_at")
            rel_path = ent.get("path")
            if isinstance(fetched_at, int) and isinstance(rel_path, str):
                age = now - fetched_at
                p = (Path(module_dir) / rel_path).resolve()
                # Only trust paths under downloads_dir.
                if age >= 0 and age <= ttl_seconds and downloads_dir.resolve() in p.parents and p.exists():
                    raw = p.read_bytes()
                    text = raw.decode("utf-8", errors="replace")[:max_chars]
                    return {
                        "success": True,
                        "result": {
                            "url": url,
                            "content_type": str(ent.get("content_type") or ""),
                            "text": text,
                            "truncated": len(raw) > max_chars,
                            "cached": True,
                            "cache_age_seconds": age,
                        },
                    }

        req = urllib.request.Request(url, headers={"User-Agent": _load_user_agent(module_dir)})
        with urllib.request.urlopen(req, timeout=20) as resp:
            content_type = resp.headers.get("content-type", "")
            raw = resp.read(max_chars + 1)

        # Persist cache.
        key = _cache_key(url)
        fname = f"{key}.bin"
        rel = f"downloads/{fname}"
        out_path = downloads_dir / fname
        out_path.write_bytes(raw)

        new_ent = {
            "url": url,
            "fetched_at": now,
            "content_type": content_type,
            "path": rel,
            "size": len(raw),
        }
        if ent is None:
            entries.append(new_ent)
        else:
            ent.clear()
            ent.update(new_ent)
        cache["entries"] = entries
        if "ttl_seconds" not in cache:
            cache["ttl_seconds"] = ttl_seconds
        _write_cache_yaml(cache_path, cache)

        text = raw.decode("utf-8", errors="replace")[:max_chars]
        return {
            "success": True,
            "result": {"url": url, "content_type": content_type, "text": text, "truncated": len(raw) > max_chars, "cached": False},
        }
    except Exception as e:
        return {"success": False, "error": str(e), "metadata": {"arguments": json.dumps(arguments, ensure_ascii=True)}}
