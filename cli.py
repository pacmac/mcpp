#!/usr/bin/env python3
"""
Human CLI for mymcp MCP server.

Usage:
    python3 cli.py list
    python3 cli.py call <tool_name> [--arg value ...]

Examples:
    python3 cli.py list
    python3 cli.py call fetch_page --url https://example.com --max_chars 5000
    python3 cli.py call spi_init
    python3 cli.py call spi_init --overwrite true
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _convert_arg_value(value: str) -> Any:
    """Convert string argument to appropriate type."""
    # Boolean
    if value.lower() in ("true", "false"):
        return value.lower() == "true"

    # Number (int or float)
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        pass

    # JSON object/array
    if value.startswith(("{", "[")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass

    # Default: string
    return value


def _communicate_with_wrapper(messages: list[dict]) -> list[dict]:
    """
    Spawn wrapper.py and send/receive JSON-RPC messages.

    Args:
        messages: List of JSON-RPC request messages

    Returns:
        List of JSON-RPC response messages
    """
    wrapper_path = Path(__file__).parent / "wrapper.py"

    # Spawn wrapper as subprocess
    proc = subprocess.Popen(
        [sys.executable, str(wrapper_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=Path.cwd(),  # Use current directory as workspace
        text=True,
    )

    # Send all messages
    input_text = "\n".join(json.dumps(msg) for msg in messages) + "\n"

    try:
        stdout, stderr = proc.communicate(input=input_text, timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("Error: Wrapper timeout", file=sys.stderr)
        sys.exit(2)

    # Parse responses
    responses = []
    for line in stdout.strip().split("\n"):
        if line.strip():
            try:
                responses.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"Error: Failed to parse wrapper response: {e}", file=sys.stderr)
                print(f"Raw output: {line}", file=sys.stderr)
                sys.exit(2)

    # Check for stderr output (wrapper errors)
    if stderr:
        print(f"Wrapper stderr:\n{stderr}", file=sys.stderr)

    return responses


def cmd_list() -> int:
    """List all available tools."""
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mymcp-cli", "version": "1.0.0"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
    ]

    responses = _communicate_with_wrapper(messages)

    # Find tools/list response (id=2)
    tools_response = None
    for resp in responses:
        if resp.get("id") == 2:
            tools_response = resp
            break

    if not tools_response:
        print("Error: No tools/list response received", file=sys.stderr)
        return 2

    if "error" in tools_response:
        print(f"Error: {tools_response['error']['message']}", file=sys.stderr)
        return 2

    tools = tools_response.get("result", {}).get("tools", [])

    if not tools:
        print("No tools available")
        return 0

    print(f"Available tools ({len(tools)}):\n")
    for tool in tools:
        name = tool.get("name", "unknown")
        desc = tool.get("description", "No description")
        schema = tool.get("inputSchema", {})
        props = schema.get("properties", {})
        required = schema.get("required", [])

        print(f"  {name}")
        print(f"    {desc}")

        if props:
            print(f"    Arguments:")
            for arg_name, arg_spec in props.items():
                arg_type = arg_spec.get("type", "any")
                arg_desc = arg_spec.get("description", "")
                req_marker = " (required)" if arg_name in required else ""
                print(f"      --{arg_name} <{arg_type}>{req_marker}")
                if arg_desc:
                    print(f"        {arg_desc}")
        print()

    return 0


def cmd_call(tool_name: str, tool_args: dict[str, Any]) -> int:
    """Call a tool with arguments."""
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mymcp-cli", "version": "1.0.0"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": tool_args,
            },
        },
    ]

    responses = _communicate_with_wrapper(messages)

    # Find tools/call response (id=2)
    call_response = None
    for resp in responses:
        if resp.get("id") == 2:
            call_response = resp
            break

    if not call_response:
        print("Error: No tools/call response received", file=sys.stderr)
        return 2

    if "error" in call_response:
        error = call_response["error"]
        print(f"Error: {error.get('message', 'Unknown error')}", file=sys.stderr)
        return 2

    result = call_response.get("result", {})

    # MCP tools/call response format
    content = result.get("content", [])
    is_error = result.get("isError", False)

    print(f"Tool: {tool_name}")
    print(f"Status: {'error' if is_error else 'success'}\n")

    if content:
        for item in content:
            if item.get("type") == "text":
                text = item.get("text", "")
                print(text)

    return 1 if is_error else 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Human CLI for mymcp MCP server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list
  %(prog)s call fetch_page --url https://example.com --max_chars 5000
  %(prog)s call spi_init
  %(prog)s call spi_init --overwrite true
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # list command
    subparsers.add_parser("list", help="List all available tools")

    # call command
    call_parser = subparsers.add_parser("call", help="Call a tool")
    call_parser.add_argument("tool_name", help="Name of the tool to call")
    call_parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Tool arguments as --key value pairs",
    )

    args = parser.parse_args()

    if args.command == "list":
        return cmd_list()

    elif args.command == "call":
        # Parse tool arguments from remaining args
        tool_args = {}
        i = 0
        while i < len(args.args):
            arg = args.args[i]

            if not arg.startswith("--"):
                print(f"Error: Expected --key, got: {arg}", file=sys.stderr)
                return 2

            key = arg[2:]  # Remove --

            # Check if next arg is the value
            if i + 1 >= len(args.args):
                print(f"Error: No value provided for --{key}", file=sys.stderr)
                return 2

            value = args.args[i + 1]
            tool_args[key] = _convert_arg_value(value)
            i += 2

        return cmd_call(args.tool_name, tool_args)

    return 2


if __name__ == "__main__":
    sys.exit(main())
