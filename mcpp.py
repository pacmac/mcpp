#!/usr/bin/env python3
"""
Minimal stdio MCP (JSON-RPC 2.0) server wrapper.

Implements the contract documented in SPEC.md:
- initialize
- tools/list
- tools/call
- ignores notifications/*
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
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import importlib.util


PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "mcpp", "version": "0.1.0"}

_shutdown_requested = False


class _ToolTimeout(Exception):
    pass


@dataclass(frozen=True)
class ModuleSource:
    import_name: str
    entry_path: Path  # either tools/<name>.py or tools/<name>/main.py
    module_dir: Path  # tools/ or tools/<name>/


@dataclass(frozen=True)
class ToolEntry:
    tool_name: str
    tool_schema: dict[str, Any]
    module: ModuleType
    module_name: str
    module_scope: str
    module_dir: str
    execute: Callable[..., dict[str, Any]]


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
    base_dir = Path(__file__).resolve().parent
    modules_path_s = os.getenv("MCPP_MODULES_PATH", "tools").strip()
    tools_dir = Path(modules_path_s)
    if not tools_dir.is_absolute():
        tools_dir = (base_dir / tools_dir).resolve()

    try:
        timeout_s = int(os.getenv("MCPP_TIMEOUT_SECONDS", "30").strip())
    except Exception:
        timeout_s = 30
    return tools_dir, timeout_s


def _iter_module_sources(tools_dir: Path) -> list[ModuleSource]:
    if not tools_dir.exists() or not tools_dir.is_dir():
        raise RuntimeError(f"tools dir not found: {tools_dir}")

    out: list[ModuleSource] = []
    for p in sorted(tools_dir.iterdir()):
        if p.name.startswith("_"):
            continue
        if not p.is_dir():
            # Enforce convention: modules are directories only (tools/<name>/main.py).
            continue

        # Package-style module: tools/<name>/main.py plus sibling files.
        main_py = p / "main.py"
        if not main_py.exists() or not main_py.is_file():
            continue
        out.append(ModuleSource(import_name=f"mcpp_tools.{p.name}", entry_path=main_py, module_dir=p))
    return out


def _import_module_from_source(src: ModuleSource) -> ModuleType:
    # For directory modules, load tools/<name>/main.py as a package module to enable relative imports.
    is_pkg = src.entry_path.name == "main.py"
    search_locations = [str(src.module_dir)] if is_pkg else None
    spec = importlib.util.spec_from_file_location(src.import_name, str(src.entry_path), submodule_search_locations=search_locations)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module spec: {src.entry_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _ensure_tools_namespace(tools_dir: Path) -> None:
    # Directory modules are loaded as packages under "mcpp_tools.<name>" and may use relative imports.
    # Ensure the parent package "mcpp_tools" exists as a namespace package.
    pkg_name = "mcpp_tools"
    if pkg_name in sys.modules:
        return
    pkg = ModuleType(pkg_name)
    pkg.__path__ = [str(tools_dir.resolve())]  # type: ignore[attr-defined]
    pkg.__package__ = pkg_name  # type: ignore[attr-defined]
    sys.modules[pkg_name] = pkg


def _normalize_scope(mod: ModuleType) -> str:
    scope = getattr(mod, "MODULE_SCOPE", "local")
    if not isinstance(scope, str):
        return "local"
    scope = scope.strip().lower()
    return scope if scope in {"local", "global"} else "local"


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
    workspace_dir: str,
) -> dict[str, Any]:
    tool_name = arguments.get("tool")

    if not tool_name:
        # List all modules' MODULE_ABOUT.
        abouts: dict[str, str] = {}
        for entry in tools_by_name.values():
            about = getattr(entry.module, "MODULE_ABOUT", None)
            if isinstance(about, str) and about.strip():
                abouts[entry.tool_name] = about
            else:
                abouts[entry.tool_name] = entry.tool_schema.get("description", "")
        return {"success": True, "result": {"tools": abouts}}

    entry = tools_by_name.get(tool_name)
    if entry is None:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    get_info_fn = getattr(entry.module, "get_info", None)
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


def discover_tools(tools_dir: Path) -> tuple[list[dict[str, Any]], dict[str, ToolEntry]]:
    tools_list: list[dict[str, Any]] = []
    tools_by_name: dict[str, ToolEntry] = {}

    loaded_modules = 0
    loaded_tools = 0

    _ensure_tools_namespace(tools_dir)

    for src in _iter_module_sources(tools_dir):
        try:
            mod = _import_module_from_source(src)
        except Exception:
            logging.warning("failed to import %s: %s", src.entry_path, traceback.format_exc().rstrip())
            continue

        module_name = getattr(mod, "MODULE_NAME", None)
        tool_defs = getattr(mod, "TOOLS", None)
        execute = getattr(mod, "execute", None)

        if not isinstance(module_name, str) or not module_name.strip():
            logging.error("skipping %s: missing/invalid MODULE_NAME", src.entry_path.name)
            continue
        if not isinstance(tool_defs, list):
            logging.error("skipping %s: missing/invalid TOOLS", src.entry_path.name)
            continue
        if not callable(execute):
            logging.error("skipping %s: missing/invalid execute()", src.entry_path.name)
            continue

        module_scope = _normalize_scope(mod)
        # For package-style modules, module_dir should be tools/<name>/, not the tools/ directory.
        module_dir = str(src.module_dir.resolve())

        # Optional module initializer.
        init_fn = getattr(mod, "initialize", None)
        if callable(init_fn):
            try:
                init_res = init_fn()
                if isinstance(init_res, dict) and init_res.get("success") is False:
                    logging.warning("module initialize() reported failure: %s (%s)", module_name, init_res.get("message"))
            except Exception:
                logging.warning("module initialize() raised: %s (%s)", module_name, traceback.format_exc().rstrip())

        for t in tool_defs:
            if not isinstance(t, dict):
                logging.error("skipping tool in %s: tool entry is not a dict", module_name)
                continue
            tool_name = t.get("name")
            if not isinstance(tool_name, str) or not tool_name.strip():
                logging.error("skipping tool in %s: missing/invalid tool name", module_name)
                continue
            if tool_name == "help":
                raise RuntimeError(f"reserved tool name 'help' used by module: {module_name}")
            if tool_name in tools_by_name:
                raise RuntimeError(f"duplicate tool name: {tool_name}")

            tools_list.append(t)
            tools_by_name[tool_name] = ToolEntry(
                tool_name=tool_name,
                tool_schema=t,
                module=mod,
                module_name=module_name,
                module_scope=module_scope,
                module_dir=module_dir,
                execute=execute,
            )
            loaded_tools += 1

        loaded_modules += 1

    # Register built-in help tool last.
    tools_list.append(_HELP_TOOL_SCHEMA)

    logging.info("loaded %d modules with %d tools (+help) from %s", loaded_modules, loaded_tools, tools_dir)
    return tools_list, tools_by_name


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
        # Back-compat: allow execute(tool_name, arguments) modules.
        try:
            sig = inspect.signature(entry.execute)
            params = list(sig.parameters.values())
            has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
            if has_varargs or len(params) >= 3:
                return entry.execute(entry.tool_name, arguments, ctx)
            return entry.execute(entry.tool_name, arguments)
        except TypeError:
            return entry.execute(entry.tool_name, arguments)

    if timeout_seconds <= 0:
        return invoke()

    # Best-effort timeout. SIGALRM is Unix-only and only works on main thread.
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
) -> dict[str, Any] | None:
    method = msg.get("method")
    id_ = msg.get("id", None)

    # Notifications: ignore (no response).
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

        # Some MCP clients expect a JSON-RPC-ish shutdown lifecycle.
        # We don't maintain state beyond "shutdown requested" and exit on "exit" notification.
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

            # Built-in help tool.
            if name == "help":
                help_res = _handle_help(arguments, tools_by_name, workspace_dir)
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
    tools_dir, timeout_seconds = _load_config()
    workspace_dir = str(Path.cwd().resolve())

    try:
        tools_list, tools_by_name = discover_tools(tools_dir)
    except Exception as e:
        logging.error("startup failed: %s", e)
        return 1

    for msg in _read_json_messages(sys.stdin):
        # JSON-RPC exit notification: used by some clients after shutdown.
        # We only honor it after a shutdown request to avoid surprising exits.
        method = msg.get("method")
        if isinstance(method, str) and method == "exit" and _shutdown_requested:
            break
        resp = handle_message(msg, tools_list, tools_by_name, workspace_dir, timeout_seconds)
        if resp is None:
            continue
        sys.stdout.write(json.dumps(resp, ensure_ascii=True, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
