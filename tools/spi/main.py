from __future__ import annotations

from pathlib import Path
from typing import Any


MODULE_NAME = "spi"
MODULE_SCOPE = "local"

TOOLS = [
    {
        "name": "spi_init",
        "description": "Create ./spi with SPEC.md, PLAN.md, IMPLEMENT.md, TASKS.md templates under the caller workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "overwrite": {"type": "boolean", "description": "Overwrite existing files if present (default: false)."}
            },
        },
    }
]


def _safe_under_root(root: Path, rel: str) -> Path:
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


def _read_template(module_dir: str, name: str) -> str:
    p = Path(module_dir) / "templates" / name
    return p.read_text(encoding="utf-8")


def execute(tool_name: str, arguments: dict[str, Any], context: dict | None = None) -> dict[str, Any]:
    try:
        if tool_name != "spi_init":
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        ctx = context or {}
        workspace_dir = ctx.get("workspace_dir")
        module_dir = ctx.get("module_dir")
        if not isinstance(workspace_dir, str) or not workspace_dir:
            return {"success": False, "error": "missing context.workspace_dir"}
        if not isinstance(module_dir, str) or not module_dir:
            return {"success": False, "error": "missing context.module_dir"}

        overwrite = bool(arguments.get("overwrite", False))

        root = Path(workspace_dir)
        spi_dir = _safe_under_root(root, "spi")
        spi_dir.mkdir(parents=True, exist_ok=True)

        files = ["SPEC.md", "PLAN.md", "IMPLEMENT.md", "TASKS.md"]
        written: list[str] = []
        skipped: list[str] = []

        for fn in files:
            out = (spi_dir / fn).resolve()
            # Ensure output stays under spi_dir.
            if spi_dir.resolve() not in out.parents:
                return {"success": False, "error": f"refusing to write outside spi dir: {out}"}

            if out.exists() and not overwrite:
                skipped.append(str(out))
                continue

            content = _read_template(module_dir, fn)
            out.write_text(content, encoding="utf-8")
            written.append(str(out))

        return {"success": True, "result": {"spi_dir": str(spi_dir), "written": written, "skipped": skipped}}
    except Exception as e:
        return {"success": False, "error": str(e)}

