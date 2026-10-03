"""Verify only the disposable Docker lab, never a merchant's production store."""
import asyncio
import json
import os
import secrets
import ssl
import subprocess
import sys

import httpx
from dotenv import dotenv_values

from scripts.demo import unused_port
from scripts.smoke import ROOT, connect, exercise
from wc_connector.client import WooCommerceClient
from wc_connector.config import Settings


async def main():
    lab = ROOT / "test-store"
    values = dotenv_values(lab / ".secrets/connector.env")
    if values.get("WC_STORE_URL") != "https://localhost:8443":
        raise RuntimeError("Provision the disposable Docker lab first; this helper only accepts its local URL.")
    credentials = json.loads((lab / ".secrets/connector.json").read_text(encoding="utf-8"))
    customer_id = credentials["customer_ids"][0]
    env = dict(os.environ, **{k: v for k, v in values.items() if v is not None})
    settings = Settings(values["WC_STORE_URL"], values["WC_CONSUMER_KEY"], values["WC_CONSUMER_SECRET"],
                        ca_bundle=values["WC_CA_BUNDLE"])
    api = WooCommerceClient(settings)
    async with connect(env=env) as session:
        stdio = await exercise(session, customer_id)
    if stdio["list_total"] != 10 or stdio["search_matches"] != 1:
        raise AssertionError("The lab should contain exactly ten fictional orders with the expected filters.")

    ids, page = [], 1
    while page is not None:
        result = await api.list(page=page, per_page=3)
        ids.extend(order.id for order in result.orders)
        page = result.next_page
    if len(ids) != 10 or len(set(ids)) != 10:
        raise AssertionError("Pagination did not return ten distinct fictional orders.")
    dates = await api.search(after="2026-01-01T00:00:00Z", before="2026-02-01T00:00:00Z")
    if dates.total != 10:
        raise AssertionError("Date filters did not match the seeded January orders.")
    text = await api.search(query=str(ids[0]))
    if ids[0] not in [order.id for order in text.orders]:
        raise AssertionError("Native order-ID text search did not match the known order.")
    empty = await api.search(customer_id=2147483647)
    if empty.orders or empty.total != 0:
        raise AssertionError("Unknown customer search should be empty.")
    order = await api.get(ids[0])
    output = order.model_dump_json()
    if any(field in output for field in ('"billing"', '"shipping"', '"email"', '"phone"', '"meta_data"', '"customer_note"')):
        raise AssertionError("Sensitive fields were returned.")

    context = ssl.create_default_context(cafile=settings.ca_bundle)
    async with httpx.AsyncClient(verify=context, timeout=15, follow_redirects=False) as http:
        wrong = await http.get(settings.orders_url, auth=httpx.BasicAuth(secrets.token_hex(20), secrets.token_hex(20)))
        if wrong.status_code not in (401, 403):
            raise AssertionError("WooCommerce accepted invalid store credentials.")
        # Nonexistent order and empty body: no existing order can be modified even if misconfigured.
        write = await http.put(settings.orders_url + "/2147483647", json={},
                               auth=httpx.BasicAuth(settings.consumer_key, settings.consumer_secret))
        if write.status_code not in (401, 403):
            raise AssertionError("WooCommerce did not reject the Read key's write attempt at authentication.")

    port = unused_port()
    url = f"http://127.0.0.1:{port}/mcp"
    process = subprocess.Popen([sys.executable, "-m", "wc_connector.server", "--transport", "http",
                                "--port", str(port)], cwd=ROOT, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with httpx.AsyncClient(timeout=1) as http:
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError("HTTP MCP server exited before readiness.")
                try:
                    missing = await http.post(url, json={})
                    if missing.status_code == 401:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(.1)
            else:
                raise RuntimeError("HTTP MCP server did not start in time.")
            wrong_http = await http.post(url, json={}, headers={"Authorization": "Bearer incorrect"})
            if wrong_http.status_code != 401:
                raise AssertionError("Incorrect HTTP connector token was accepted.")
        async with connect("http", url, env) as session:
            remote = await exercise(session, customer_id)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    report = {"backend": "Real WooCommerce 10.2.2 / WordPress 6.8.3 local Docker lab",
              "data": "10 fictional orders; locally generated credentials excluded",
              "tls_certificate_verified": True, "stdio": stdio, "http": remote,
              "all_pages_read": True, "distinct_orders": len(set(ids)),
              "date_filter_matches": dates.total, "native_order_id_search_passed": True,
              "empty_search_passed": True, "sensitive_fields_excluded": True,
              "invalid_store_credentials_status": wrong.status_code,
              "read_key_write_rejected_status": write.status_code,
              "missing_and_wrong_http_tokens_rejected": True}
    (ROOT / "LIVE_VALIDATION.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
