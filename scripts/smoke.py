import argparse
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def connect(transport="stdio", url="http://127.0.0.1:8000/mcp", env=None):
    if transport == "stdio":
        params = StdioServerParameters(command=sys.executable, args=["-m", "wc_connector.server"],
                                      cwd=str(ROOT), env=env or dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    else:
        token = (env or os.environ).get("MCP_BEARER_TOKEN", "")
        if not token:
            raise RuntimeError("Set MCP_BEARER_TOKEN before HTTP testing.")
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=70) as http:
            async with streamable_http_client(url, http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session


async def exercise(session, customer_id=101):
    tools = (await session.list_tools()).tools
    actual = [tool.model_dump(mode="json", exclude_none=True) for tool in tools]
    expected = json.loads((ROOT / "mcp-tools.json").read_text(encoding="utf-8"))["tools"]
    if actual != expected:
        raise AssertionError("Runtime tools differ from mcp-tools.json")

    async def call(name, arguments):
        result = await session.call_tool(name, arguments)
        if result.isError or result.structuredContent is None:
            raise AssertionError(f"{name} failed or returned no structured content")
        return result.structuredContent

    first = await call("list_orders", {"per_page": 3})
    if not first["orders"]:
        raise AssertionError("Seed fictional orders before running the smoke test")
    order = await call("get_order", {"order_id": first["orders"][0]["id"]})
    search = await call("search_orders", {"customer_id": customer_id, "status": "processing"})
    if any(o["customer_id"] != customer_id or o["status"] != "processing" for o in search["orders"]):
        raise AssertionError("Combined filters failed")
    bad = await session.call_tool("search_orders", {})
    if not bad.isError:
        raise AssertionError("Empty search must be rejected")
    missing = await session.call_tool("get_order", {"order_id": 2147483647})
    if not missing.isError:
        raise AssertionError("Missing order must return a tool error")
    return {"tool_names": [t.name for t in tools], "list_total": first["total"],
            "first_order_id": order["id"], "search_matches": len(search["orders"]),
            "invalid_search_rejected": True, "missing_order_rejected": True,
            "spec_matches_runtime": True}


async def main_async(args):
    async with connect(args.transport, args.url) as session:
        report = await exercise(session, args.customer_id)
        print(json.dumps(report, indent=2))


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Smoke-test the real MCP protocol with fictional orders")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--customer-id", type=int, default=101)
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
