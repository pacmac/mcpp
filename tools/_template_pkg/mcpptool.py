"""
Package-style module template (ignored by wrapper because directory starts with "_").

Copy this directory to `tools/<your_module>/` to start a new tool module.
The contract is defined in tool.yaml — mcpptool.py only needs execute().
"""

from __future__ import annotations

from typing import Any

from .helper import VALUE


def get_info(context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Optional: return runtime configuration for agent discoverability."""
    return {"params": {}}


def execute(tool_name: str, arguments: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    if tool_name != "template_pkg_value":
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
    return {"success": True, "result": {"value": VALUE, "module_dir": (context or {}).get("module_dir")}}
