from __future__ import annotations

from pathlib import Path
from typing import Any

MODULE_NAME = "scaffold"
MODULE_SCOPE = "local"

TOOLS = [
    {
        "name": "scaffold_mkdir",
        "description": "Create a directory under the workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "scaffold_write_text",
        "description": "Write a UTF-8 text file under the workspace (creates parent dirs).",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "scaffold_read_text",
        "description": "Read a UTF-8 text file under the workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "scaffold_where",
        "description": "Return the workspace_dir and module_dir seen by this tool.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _safe_under_root(root: Path, rel: str) -> Path:
    # Resolve against the workspace root, and prevent escaping via ../
    rel_p = Path(rel)
    if rel_p.is_absolute():
        raise ValueError("path must be relative")
    target = (root / rel_p).resolve()
    root_r = root.resolve()
    if target == root_r:
        return target
    if root_r not in target.parents:
        raise ValueError("path escapes workspace")
    return target


def execute(tool_name: str, arguments: dict[str, Any], context: dict | None = None) -> dict[str, Any]:
    try:
        ctx = context or {}
        workspace_dir = ctx.get("workspace_dir")
        if not isinstance(workspace_dir, str) or not workspace_dir:
            return {"success": False, "error": "missing context.workspace_dir"}
        root = Path(workspace_dir)

        if tool_name == "scaffold_mkdir":
            p = _safe_under_root(root, str(arguments["path"]))
            p.mkdir(parents=True, exist_ok=True)
            return {"success": True, "result": {"created": str(p)}}

        if tool_name == "scaffold_write_text":
            p = _safe_under_root(root, str(arguments["path"]))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(arguments["content"]), encoding="utf-8")
            return {"success": True, "result": {"written": str(p)}}

        if tool_name == "scaffold_read_text":
            p = _safe_under_root(root, str(arguments["path"]))
            return {"success": True, "result": {"path": str(p), "content": p.read_text(encoding="utf-8")}}

        if tool_name == "scaffold_where":
            return {
                "success": True,
                "result": {"workspace_dir": workspace_dir, "module_dir": ctx.get("module_dir"), "module_scope": ctx.get("module_scope")},
            }

        return {"success": False, "error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

