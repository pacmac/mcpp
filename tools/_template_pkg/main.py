"""
Package-style module template (ignored by wrapper because directory starts with "_").

Copy this directory to `tools/<your_module>/` to start a module that can include sibling files.
Entry point must be `main.py`.
"""

from __future__ import annotations

from typing import Any

from .helper import VALUE

MODULE_NAME = "template_pkg"  # change me
MODULE_SCOPE = "global"  # or "local"
MODULE_ABOUT = "Short description of what this module does and when to use it."  # change me

TOOLS: list[dict[str, Any]] = [
    {
        "name": "template_pkg_value",
        "description": "Return a value from a sibling module (example).",
        "inputSchema": {"type": "object", "properties": {}},
    }
]


def get_info(context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return runtime configuration for agent discoverability (see SPEC.md §1.3)."""
    return {"params": {}}


def execute(tool_name: str, arguments: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    if tool_name != "template_pkg_value":
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
    return {"success": True, "result": {"value": VALUE, "module_dir": (context or {}).get("module_dir")}}

