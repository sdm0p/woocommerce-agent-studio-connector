import json

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from scripts.smoke import ROOT
from wc_connector.client import WooCommerceClient
from wc_connector.config import Settings
from wc_connector.server import BearerAuth, create_server

SETTINGS = Settings("https://example.invalid", "key", "secret")


async def test_spec_matches_tools_and_annotations():
    tools = await create_server(SETTINGS).list_tools()
    assert {t.name for t in tools} == {"list_orders", "get_order", "search_orders"}
    assert [t.model_dump(mode="json", exclude_none=True) for t in tools] == json.loads(
        (ROOT / "mcp-tools.json").read_text(encoding="utf-8"))["tools"]
    for tool in tools:
        assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
        assert tool.outputSchema is not None


@pytest.mark.parametrize("name,args", [("get_order", {"order_id": "secret-input"}),
    ("get_order", {"order_id": True}), ("get_order", {"order_id": -1}),
    ("list_orders", {"per_page": 101}), ("list_orders", {"url": "https://evil.invalid"}),
    ("search_orders", {"status": "secret-input"}), ("delete_order", {"order_id": 1})])
async def test_invalid_mcp_inputs_are_sanitized(name, args):
    with pytest.raises(ToolError) as caught:
        await create_server(SETTINGS).call_tool(name, args)
    assert "secret-input" not in str(caught.value) and "evil.invalid" not in str(caught.value)


async def test_upstream_error_stays_sanitized_at_mcp_boundary():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(401, json={"secret": "DO-NOT-LEAK"}))) as http:
        server = create_server(SETTINGS, WooCommerceClient(SETTINGS, http))
        with pytest.raises(ToolError, match="authentication failed") as caught:
            await server.call_tool("get_order", {"order_id": 1})
    assert "DO-NOT-LEAK" not in str(caught.value)


async def test_http_bearer_auth_gate():
    calls = []
    async def app(scope, receive, send):
        calls.append(scope["path"])
        from starlette.responses import JSONResponse
        await JSONResponse({"ok": True})(scope, receive, send)
    token = "x" * 40
    wrapped = BearerAuth(app, token)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://localhost") as http:
        assert (await http.post("/mcp", json={})).status_code == 401
        assert (await http.post("/mcp", headers={"Authorization": "Bearer wrong"}, json={})).status_code == 401
        assert (await http.post("/mcp", headers=[("Authorization", "Bearer " + token),
                                                 ("Authorization", "Bearer " + token)], json={})).status_code == 401
        assert (await http.post("/mcp", headers={"Authorization": "Bearer " + token}, json={})).status_code == 200
    assert calls == ["/mcp"]


def test_http_refuses_weak_or_placeholder_token():
    for token in ("", "weak", "replace-with-a-random-token-at-least-32-characters"):
        with pytest.raises(ValueError):
            BearerAuth(None, token)
