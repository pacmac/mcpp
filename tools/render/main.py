from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

MODULE_NAME = "render"
MODULE_SCOPE = "local"
MODULE_ABOUT = "Renders web pages via Playwright and returns metadata, text, and structure. Use when you need to inspect how a page looks or behaves."

TOOLS = [
    {
        "name": "render",
        "description": "Render a page using rendermod (Playwright-based). Requires render.yaml in the workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page": {"type": "string", "description": "Page name or path to render"},
                "device": {"type": "string", "description": "Device type: mobile, tablet, or desktop"},
                "args": {"type": "object", "description": "Query-string overrides as key-value pairs"},
            },
            "required": ["page"],
        },
    }
]

def _ensure_rendermod_importable() -> None:
    """Add rendermod to sys.path, looking relative to this module location."""
    # Try to find rendermod as sibling of mcpp
    mcpp_dir = Path(__file__).resolve().parent.parent.parent  # tools/render/main.py -> mcpp
    parent_dir = mcpp_dir.parent  # mcpp -> parent
    rendermod_dir = parent_dir / "rendermod"
    
    if rendermod_dir.exists() and str(rendermod_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))


def get_info(context: dict[str, Any] | None = None) -> dict[str, Any]:
    workspace_dir = (context or {}).get("workspace_dir")
    if not workspace_dir:
        return {"params": {}}

    _ensure_rendermod_importable()

    try:
        from rendermod.config import load_config
        config = load_config(Path(workspace_dir))
    except Exception:
        return {"params": {}}

    pages = list(config.get("pages", {}).keys())
    defaults = config.get("defaults", {})
    devices = ["mobile", "desktop", "tablet"]

    params: dict[str, Any] = {
        "page": {"values": pages, "default": None},
        "device": {"values": devices, "default": defaults.get("device", "mobile")},
    }

    # Expose available args if config defines them.
    args_conf = config.get("args", {})
    if isinstance(args_conf, dict) and args_conf.get("values"):
        params["args"] = {
            "values": args_conf["values"],
            "default": args_conf.get("default"),
        }

    info: dict[str, Any] = {"params": params}
    if config.get("base_url"):
        info["base_url"] = config["base_url"]
    if "auth" in config:
        info["has_auth"] = True
    return info


_STRIP_KEYS = {"html", "screenshot"}


def execute(tool_name: str, arguments: dict[str, Any], context: dict | None = None) -> dict[str, Any]:
    try:
        if tool_name != "render":
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        page = str(arguments["page"])
        device = arguments.get("device")
        override_args = arguments.get("args")
        workspace_dir = (context or {}).get("workspace_dir")

        _ensure_rendermod_importable()

        from rendermod.config import load_config
        from rendermod.renderer import Renderer

        config_dir = Path(workspace_dir) if workspace_dir else None
        config = load_config(config_dir)
        renderer = Renderer(config, config_path=config_dir / "render.yaml" if config_dir else None)
        try:
            result = renderer.render(page, device=device, override_args=override_args, return_data=True)
        finally:
            renderer.cleanup()

        if result is None:
            return {"success": False, "error": "render() returned None"}

        filtered = {k: v for k, v in result.items() if k not in _STRIP_KEYS}
        return {"success": True, "result": filtered}
    except Exception as e:
        return {"success": False, "error": str(e)}
