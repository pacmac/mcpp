from __future__ import annotations

from pathlib import Path
from typing import Any



def get_info(context: dict[str, Any] | None = None) -> dict[str, Any]:
    # List existing plans if workspace_dir available.
    existing: list[str] = []
    workspace_dir = (context or {}).get("workspace_dir")
    if workspace_dir:
        what_dir = Path(workspace_dir) / "what"
        if what_dir.is_dir():
            existing = sorted(p.name for p in what_dir.iterdir() if p.is_dir() and not p.name.startswith("_"))
    return {
        "params": {
            "name": {"values": None, "default": None},
            "overwrite": {"values": [True, False], "default": False},
        },
        "existing_plans": existing,
        "creates": "what/<name>/WHAT.md, what/<name>/HOW.md, what/<name>/ACTIONS.md, what/<name>/TASKS.md",
    }


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
        if tool_name != "what_add":
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        ctx = context or {}
        workspace_dir = ctx.get("workspace_dir")
        module_dir = ctx.get("module_dir")
        if not isinstance(workspace_dir, str) or not workspace_dir:
            return {"success": False, "error": "missing context.workspace_dir"}
        if not isinstance(module_dir, str) or not module_dir:
            return {"success": False, "error": "missing context.module_dir"}

        name = arguments.get("name")
        if not isinstance(name, str) or not name.strip():
            return {"success": False, "error": "missing required argument: name"}
        name = name.strip()
        overwrite = bool(arguments.get("overwrite", False))

        root = Path(workspace_dir)
        what_dir = _safe_under_root(root, "what")
        plan_dir = _safe_under_root(what_dir, name)
        plan_dir.mkdir(parents=True, exist_ok=True)

        # Drop README.md in what/ root on first use.
        readme = what_dir / "README.md"
        if not readme.exists():
            readme.write_text(_read_template(module_dir, "README.md"), encoding="utf-8")

        files = ["WHAT.md", "HOW.md", "ACTIONS.md", "TASKS.md"]
        written: list[str] = []
        skipped: list[str] = []

        for fn in files:
            out = (plan_dir / fn).resolve()
            # Ensure output stays under plan_dir.
            if plan_dir.resolve() not in out.parents:
                return {"success": False, "error": f"refusing to write outside plan dir: {out}"}

            if out.exists() and not overwrite:
                skipped.append(str(out))
                continue

            content = _read_template(module_dir, fn)
            out.write_text(content, encoding="utf-8")
            written.append(str(out))

        return {"success": True, "result": {"plan_dir": str(plan_dir), "written": written, "skipped": skipped}}
    except Exception as e:
        return {"success": False, "error": str(e)}

