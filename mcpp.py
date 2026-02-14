#!/usr/bin/env python3
"""
Minimal stdio MCP (JSON-RPC 2.0) server wrapper.

Tool modules declare their contract via tool.yaml manifests.
Python code is only loaded lazily on first tool call.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import signal
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import importlib.util

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "mcpp", "version": "0.2.0"}

_shutdown_requested = False


class _ToolTimeout(Exception):
    pass


@dataclass(frozen=True)
class ManifestEntry:
    """Parsed tool.yaml manifest for a single module directory."""
    name: str
    scope: str
    about: str
    tools: list[dict[str, Any]]
    module_dir: Path


@dataclass
class ToolEntry:
    """Runtime entry for a registered tool, with lazy-loaded module."""
    tool_name: str
    tool_schema: dict[str, Any]
    module_name: str
    module_scope: str
    module_dir: str
    _module: ModuleType | None = field(default=None, repr=False)
    _execute: Callable[..., dict[str, Any]] | None = field(default=None, repr=False)

    def load_module(self) -> None:
        """Import the module's mcpptool.py and resolve execute()."""
        if self._module is not None:
            return
        mod_dir = Path(self.module_dir)
        main_py = mod_dir / "mcpptool.py"
        if not main_py.exists():
            raise ImportError(f"mcpptool.py not found in {mod_dir}")

        import_name = f"mcpp_tools.{mod_dir.name}"
        spec = importlib.util.spec_from_file_location(
            import_name, str(main_py),
            submodule_search_locations=[str(mod_dir)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load module spec: {main_py}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[import_name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        execute = getattr(mod, "execute", None)
        if not callable(execute):
            raise ImportError(f"module {self.module_name} has no execute() function")

        # Optional initializer.
        init_fn = getattr(mod, "initialize", None)
        if callable(init_fn):
            try:
                init_res = init_fn()
                if isinstance(init_res, dict) and init_res.get("success") is False:
                    logging.warning("module initialize() reported failure: %s (%s)", self.module_name, init_res.get("message"))
            except Exception:
                logging.warning("module initialize() raised: %s (%s)", self.module_name, traceback.format_exc().rstrip())

        self._module = mod
        self._execute = execute

    @property
    def module(self) -> ModuleType:
        if self._module is None:
            self.load_module()
        return self._module  # type: ignore[return-value]

    @property
    def execute(self) -> Callable[..., dict[str, Any]]:
        if self._execute is None:
            self.load_module()
        return self._execute  # type: ignore[return-value]


def _setup_logging() -> None:
    level_s = os.getenv("MCPP_LOG_LEVEL", "info").lower().strip()
    level = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }.get(level_s, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


def _load_config() -> tuple[Path, int]:
    # Base directory for resolving tools.yaml and relative module paths.
    # Defaults to the directory containing mcpp.py.
    base_dir_s = os.getenv("MCPP_BASE_DIR", "").strip()
    if base_dir_s:
        base_dir = Path(base_dir_s).resolve()
    else:
        base_dir = Path(__file__).resolve().parent

    try:
        timeout_s = int(os.getenv("MCPP_TIMEOUT_SECONDS", "30").strip())
    except Exception:
        timeout_s = 30
    return base_dir, timeout_s


# ── Manifest parsing ──

def _parse_yaml(text: str) -> Any:
    """Parse YAML text using PyYAML if available, else a minimal parser."""
    if yaml is not None:
        return yaml.safe_load(text)
    raise RuntimeError("PyYAML is required: pip install pyyaml")


def _load_manifest(yaml_path: Path) -> ManifestEntry:
    """Parse and validate a tool.yaml manifest."""
    text = yaml_path.read_text(encoding="utf-8")
    data = _parse_yaml(text)

    if not isinstance(data, dict):
        raise ValueError(f"tool.yaml must be a YAML mapping, got {type(data).__name__}")

    # Required fields.
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("tool.yaml: 'name' is required and must be a non-empty string")

    tools = data.get("tools")
    if not isinstance(tools, list) or not tools:
        raise ValueError("tool.yaml: 'tools' is required and must be a non-empty list")

    # Validate each tool entry.
    for i, t in enumerate(tools):
        if not isinstance(t, dict):
            raise ValueError(f"tool.yaml: tools[{i}] must be a mapping")
        tname = t.get("name")
        if not isinstance(tname, str) or not tname.strip():
            raise ValueError(f"tool.yaml: tools[{i}].name is required")
        if "description" not in t:
            raise ValueError(f"tool.yaml: tools[{i}].description is required")
        if "inputSchema" not in t:
            raise ValueError(f"tool.yaml: tools[{i}].inputSchema is required")

    # Optional fields.
    scope = data.get("scope", "local")
    if not isinstance(scope, str) or scope.strip().lower() not in {"local", "global"}:
        raise ValueError(f"tool.yaml: 'scope' must be 'local' or 'global', got {scope!r}")
    scope = scope.strip().lower()

    about = data.get("about", "")
    if not isinstance(about, str):
        about = ""

    module_dir = yaml_path.parent
    return ManifestEntry(name=name.strip(), scope=scope, about=about.strip(), tools=tools, module_dir=module_dir)


# ── Registry ──

def _load_registry(base_dir: Path) -> list[Path]:
    """Read tools.yaml and return resolved module directory paths."""
    registry_path = base_dir / "tools.yaml"
    if not registry_path.exists():
        raise RuntimeError(f"tools.yaml not found at {registry_path}")

    text = registry_path.read_text(encoding="utf-8")
    data = _parse_yaml(text)

    if not isinstance(data, dict):
        raise ValueError(f"tools.yaml must be a YAML mapping, got {type(data).__name__}")

    modules = data.get("modules")
    if not isinstance(modules, list) or not modules:
        raise ValueError("tools.yaml: 'modules' is required and must be a non-empty list")

    paths: list[Path] = []
    for i, entry in enumerate(modules):
        if not isinstance(entry, dict):
            raise ValueError(f"tools.yaml: modules[{i}] must be a mapping with 'path'")
        path_s = entry.get("path")
        if not isinstance(path_s, str) or not path_s.strip():
            raise ValueError(f"tools.yaml: modules[{i}].path is required")

        p = Path(path_s.strip())
        if not p.is_absolute():
            p = (base_dir / p).resolve()
        paths.append(p)

    return paths


# ── Discovery ──

def _ensure_tools_namespace() -> None:
    pkg_name = "mcpp_tools"
    if pkg_name in sys.modules:
        return
    pkg = ModuleType(pkg_name)
    pkg.__path__ = []  # type: ignore[attr-defined]
    pkg.__package__ = pkg_name  # type: ignore[attr-defined]
    sys.modules[pkg_name] = pkg


_HELP_TOOL_SCHEMA: dict[str, Any] = {
    "name": "help",
    "description": (
        "Lists available tools and their capabilities. "
        "Call with no arguments to see all tools, or with tool=<name> to get "
        "runtime options for a specific tool. Call this before using unfamiliar tools."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "tool": {
                "type": "string",
                "description": "Tool name to get detailed info for. Omit to list all tools.",
            }
        },
    },
}


def _handle_help(
    arguments: dict[str, Any],
    tools_by_name: dict[str, ToolEntry],
    manifests: dict[str, ManifestEntry],
    workspace_dir: str,
) -> dict[str, Any]:
    tool_name = arguments.get("tool")

    if not tool_name:
        # List all tools from manifests (no module import needed).
        abouts: dict[str, str] = {}
        for mname, manifest in manifests.items():
            for t in manifest.tools:
                tname = t["name"]
                if manifest.about:
                    abouts[tname] = manifest.about
                else:
                    abouts[tname] = t.get("description", "")
        return {"success": True, "result": {"tools": abouts}}

    entry = tools_by_name.get(tool_name)
    if entry is None:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    # get_info requires module import (lazy load).
    try:
        get_info_fn = getattr(entry.module, "get_info", None)
    except ImportError as e:
        return {"success": False, "error": f"Failed to load module: {e}"}

    if not callable(get_info_fn):
        return {"success": True, "result": {"params": {}}}

    ctx = {
        "workspace_dir": workspace_dir,
        "module_dir": entry.module_dir,
        "module_scope": entry.module_scope,
    }
    try:
        info = get_info_fn(ctx)
    except Exception:
        return {"success": False, "error": f"get_info() failed: {traceback.format_exc().rstrip()}"}

    if not isinstance(info, dict):
        return {"success": True, "result": {"params": {}}}
    return {"success": True, "result": info}


def discover_tools(base_dir: Path) -> tuple[list[dict[str, Any]], dict[str, ToolEntry], dict[str, ManifestEntry]]:
    """Discover tools from tools.yaml registry + tool.yaml manifests. No Python imports happen here."""
    tools_list: list[dict[str, Any]] = []
    tools_by_name: dict[str, ToolEntry] = {}
    manifests: dict[str, ManifestEntry] = {}

    _ensure_tools_namespace()

    module_paths = _load_registry(base_dir)

    loaded_modules = 0
    loaded_tools = 0

    for p in module_paths:
        if not p.is_dir():
            logging.warning("skipping %s: directory not found", p)
            continue

        yaml_path = p / "tool.yaml"
        if not yaml_path.exists():
            logging.warning("skipping %s: no tool.yaml", p)
            continue

        try:
            manifest = _load_manifest(yaml_path)
        except Exception as e:
            logging.warning("skipping %s: invalid tool.yaml: %s", p, e)
            continue

        main_py = p / "mcpptool.py"
        if not main_py.exists():
            logging.warning("skipping %s: tool.yaml found but no mcpptool.py", p)
            continue

        manifests[manifest.name] = manifest
        module_dir = str(manifest.module_dir.resolve())

        for t in manifest.tools:
            tname = t["name"]
            if tname == "help":
                raise RuntimeError(f"reserved tool name 'help' used by module: {manifest.name}")
            if tname in tools_by_name:
                raise RuntimeError(f"duplicate tool name: {tname}")

            tools_list.append(t)
            tools_by_name[tname] = ToolEntry(
                tool_name=tname,
                tool_schema=t,
                module_name=manifest.name,
                module_scope=manifest.scope,
                module_dir=module_dir,
            )
            loaded_tools += 1

        loaded_modules += 1

    # Register built-in help tool last.
    tools_list.append(_HELP_TOOL_SCHEMA)

    logging.info("discovered %d modules with %d tools (+help) from registry", loaded_modules, loaded_tools)
    return tools_list, tools_by_name, manifests


def _jsonrpc_response(id_: Any, result: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    resp: dict[str, Any] = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        resp["error"] = error
    else:
        resp["result"] = result
    return resp


def _jsonrpc_error(code: int, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}


def _content_text(payload: Any, audience: list[str] | None = None) -> dict[str, Any]:
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    item: dict[str, Any] = {"type": "text", "text": text}
    if audience:
        item["annotations"] = {"audience": audience}
    return item


def _build_content(tool_res: dict[str, Any]) -> list[dict[str, Any]]:
    """Build MCP content list from a tool result.

    If tool_res has a "display" key, return two content items:
    - human-readable text for the user (audience: ["user"])
    - structured JSON for the assistant (audience: ["assistant"])
    Otherwise return a single content item with no audience filter.
    """
    display = tool_res.get("display")
    result = tool_res.get("result")
    if display:
        return [
            _content_text(display, audience=["user"]),
            _content_text(result, audience=["assistant"]),
        ]
    return [_content_text(result)]


def _call_execute(entry: ToolEntry, arguments: dict[str, Any], workspace_dir: str, timeout_seconds: int) -> dict[str, Any]:
    ctx = {
        "workspace_dir": workspace_dir,
        "module_dir": entry.module_dir,
        "module_scope": entry.module_scope,
    }

    def invoke() -> dict[str, Any]:
        execute_fn = entry.execute  # triggers lazy load
        try:
            sig = inspect.signature(execute_fn)
            params = list(sig.parameters.values())
            has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
            if has_varargs or len(params) >= 3:
                return execute_fn(entry.tool_name, arguments, ctx)
            return execute_fn(entry.tool_name, arguments)
        except TypeError:
            return execute_fn(entry.tool_name, arguments)

    if timeout_seconds <= 0:
        return invoke()

    if hasattr(signal, "SIGALRM"):
        old = signal.getsignal(signal.SIGALRM)

        def _alarm_handler(signum: int, frame: Any) -> None:  # pragma: no cover
            raise _ToolTimeout()

        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, float(timeout_seconds))
        try:
            return invoke()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, old)

    return invoke()


def handle_message(
    msg: dict[str, Any],
    tools_list: list[dict[str, Any]],
    tools_by_name: dict[str, ToolEntry],
    workspace_dir: str,
    timeout_seconds: int,
    manifests: dict[str, ManifestEntry] | None = None,
) -> dict[str, Any] | None:
    method = msg.get("method")
    id_ = msg.get("id", None)

    if id_ is None:
        return None

    if msg.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return _jsonrpc_response(id_, error=_jsonrpc_error(-32600, "Invalid Request"))

    try:
        if method == "initialize":
            return _jsonrpc_response(
                id_,
                result={
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": SERVER_INFO,
                },
            )

        if method == "shutdown":
            global _shutdown_requested
            _shutdown_requested = True
            return _jsonrpc_response(id_, result=None)

        if method == "tools/list":
            return _jsonrpc_response(id_, result={"tools": tools_list})

        if method == "tools/call":
            params = msg.get("params") or {}
            if not isinstance(params, dict):
                return _jsonrpc_response(id_, error=_jsonrpc_error(-32602, "Invalid params"))
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return _jsonrpc_response(id_, error=_jsonrpc_error(-32602, "Invalid params"))

            if name == "help":
                help_res = _handle_help(arguments, tools_by_name, manifests or {}, workspace_dir)
                if help_res.get("success") is True:
                    return _jsonrpc_response(id_, result={"content": [_content_text(help_res.get("result"))]})
                err_text = help_res.get("error") or "Unknown error"
                return _jsonrpc_response(
                    id_,
                    result={"content": [_content_text(f"Error: {err_text}")], "isError": True},
                )

            entry = tools_by_name.get(name)
            if entry is None:
                return _jsonrpc_response(
                    id_,
                    result={"content": [_content_text(f"Error: Unknown tool: {name}")], "isError": True},
                )

            start = time.time()
            try:
                tool_res = _call_execute(entry, arguments, workspace_dir, timeout_seconds)
            except _ToolTimeout:
                tool_res = {"success": False, "error": f"Timeout after {timeout_seconds}s"}
            except Exception:
                tool_res = {"success": False, "error": traceback.format_exc().rstrip()}
            elapsed_ms = int((time.time() - start) * 1000)
            logging.info("[tools/call] tool=%s ms=%d", name, elapsed_ms)

            if not isinstance(tool_res, dict):
                tool_res = {"success": False, "error": "tool returned non-dict result"}

            if tool_res.get("success") is True:
                return _jsonrpc_response(id_, result={"content": _build_content(tool_res)})

            err_text = tool_res.get("error") or "Unknown error"
            return _jsonrpc_response(
                id_,
                result={"content": [_content_text(f"Error: {err_text}")], "isError": True},
            )

        if method.startswith("notifications/"):
            return None

        return _jsonrpc_response(id_, error=_jsonrpc_error(-32601, "Method not found"))

    except Exception:
        logging.error("internal error handling method=%s: %s", method, traceback.format_exc().rstrip())
        return _jsonrpc_response(id_, error=_jsonrpc_error(-32603, "Internal error"))


def _read_json_messages(stream: Any) -> Any:
    buf = ""
    for line in stream:
        if not line:
            continue
        buf += line
        if not buf.strip():
            buf = ""
            continue
        try:
            msg = json.loads(buf)
        except json.JSONDecodeError:
            continue
        buf = ""
        if isinstance(msg, dict):
            yield msg


def main() -> int:
    _setup_logging()
    base_dir, timeout_seconds = _load_config()
    workspace_dir = str(Path.cwd().resolve())

    try:
        tools_list, tools_by_name, manifests = discover_tools(base_dir)
    except Exception as e:
        logging.error("startup failed: %s", e)
        return 1

    for msg in _read_json_messages(sys.stdin):
        method = msg.get("method")
        if isinstance(method, str) and method == "exit" and _shutdown_requested:
            break
        resp = handle_message(msg, tools_list, tools_by_name, workspace_dir, timeout_seconds, manifests)
        if resp is None:
            continue
        sys.stdout.write(json.dumps(resp, ensure_ascii=True, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
