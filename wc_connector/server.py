import argparse
import hmac
import logging
import os
import sys
from typing import Annotated, Literal

import uvicorn
import jsonschema
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.responses import JSONResponse

from .client import ConnectorError, WooCommerceClient
from .config import Settings
from .models import OrderPage, OrderSummary

Positive = Annotated[int, Field(strict=True, gt=0)]
PageSize = Annotated[int, Field(strict=True, ge=1, le=100)]
Status = Literal["pending", "processing", "on-hold", "completed", "cancelled", "refunded", "failed", "trash", "any"]


class SanitizedMCP(FastMCP):
    async def list_tools(self):
        tools = await super().list_tools()
        for tool in tools:
            tool.inputSchema["additionalProperties"] = False
        return tools

    async def call_tool(self, name, arguments):
        tool = next((t for t in await self.list_tools() if t.name == name), None)
        if tool is None:
            raise ToolError("Unknown tool; discover available tools before calling.")
        if set(arguments) - set(tool.inputSchema.get("properties", {})):
            raise ToolError("Unexpected tool input; only documented parameters are accepted.")
        try:
            jsonschema.validate(arguments, tool.inputSchema)
        except jsonschema.ValidationError:
            raise ToolError("Invalid tool inputs; check the documented types and limits.") from None
        try:
            return await super().call_tool(name, arguments)
        except ToolError as exc:
            current = exc
            seen = set()
            while current is not None and id(current) not in seen:
                seen.add(id(current))
                if isinstance(current, ConnectorError):
                    raise ToolError(str(current)) from None
                current = current.__cause__ or current.__context__
            raise ToolError("Connector could not complete the request; check inputs and configuration.") from None


def create_server(settings: Settings, client: WooCommerceClient | None = None):
    api = client or WooCommerceClient(settings)
    mcp = SanitizedMCP("WooCommerce read-only orders", stateless_http=True, json_response=True, log_level="WARNING")
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)

    async def safe(awaitable):
        try:
            return await awaitable
        except ConnectorError as exc:
            raise ToolError(str(exc)) from None
        except Exception:
            raise ToolError("Connector could not complete the request; check configuration and try again.") from None

    @mcp.tool(annotations=annotations)
    async def list_orders(page: Positive = 1, per_page: PageSize = 20) -> OrderPage:
        """Browse orders one page at a time. Follow next_page to read all pages; no edits are possible."""
        return await safe(api.list(page, per_page))

    @mcp.tool(annotations=annotations)
    async def get_order(order_id: Positive) -> OrderSummary:
        """Read one order by its numeric WooCommerce order ID; returns a limited order summary."""
        return await safe(api.get(order_id))

    @mcp.tool(annotations=annotations)
    async def search_orders(
        customer_id: Positive | None = None, status: Status | None = None,
        query: Annotated[str, Field(min_length=1, max_length=200)] | None = None,
        after: str | None = None, before: str | None = None,
        page: Positive = 1, per_page: PageSize = 20,
    ) -> OrderPage:
        """Find orders using combined filters (AND). Supply at least one filter. customer_id is a registered customer ID, not a name/email; guest ID 0 cannot be filtered. query uses native WooCommerce text search, not exact customer lookup. Dates require ISO8601 with timezone and are normalized to UTC."""
        return await safe(api.search(customer_id, status, query, after, before, page, per_page))

    return mcp


class BearerAuth:
    """Private API-key gate; not an OAuth authorization server."""

    def __init__(self, app, token: str):
        if len(token) < 32 or token.startswith("replace-with"):
            raise ValueError("MCP_BEARER_TOKEN must be a locally generated random token of at least 32 characters.")
        self.app, self.expected = app, ("Bearer " + token).encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            auth = [v for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
            if len(auth) != 1 or not hmac.compare_digest(auth[0], self.expected):
                response = JSONResponse({"error": "Unauthorized"}, status_code=401,
                                        headers={"WWW-Authenticate": "Bearer"})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def main():
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Read-only WooCommerce MCP server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    load_dotenv()
    try:
        mcp = create_server(Settings.from_env())
        if args.transport == "stdio":
            mcp.run(transport="stdio")
        else:
            app = BearerAuth(mcp.streamable_http_app(), os.environ.get("MCP_BEARER_TOKEN", ""))
            uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
