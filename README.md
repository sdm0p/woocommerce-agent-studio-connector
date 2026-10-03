# WooCommerce read-only order connector

A private, single-store MCP connector for **assignment 3: Build a private connector for a merchant tool**. An agent can browse orders, read one order, and search by registered customer ID, status, native search text, or creation dates. It cannot change orders.

**Verified:** 60 automated tests on Python 3.12 and 3.14, real MCP calls through both transports, and real WooCommerce 10.2.2 with ten fictional orders over certificate-verified HTTPS. WooCommerce rejected invalid keys and a Read key's write attempt with HTTP 401. See [LIVE_VALIDATION.json](LIVE_VALIDATION.json) for the sanitized live-test report. Agent Studio itself remains unverified because platform access was unavailable.

**Review in a few minutes:** install dependencies, run the fictional-data demo, and run the tests. No WooCommerce account, LLM key, paid service, or customer data is required for that path. The demo speaks real MCP but uses a clearly labeled WooCommerce API simulator. An optional Docker lab exercises real WooCommerce.

## Quick start (Windows PowerShell)

Open a terminal in the extracted `woocommerce-connector` folder. Python 3.12 or newer is required.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m scripts.demo
.\.venv\Scripts\python.exe -m pytest -q
```

The demo generates credentials in memory, starts a fictional store, launches the stdio MCP server, and then launches the HTTP MCP server. It discovers the three tools, calls each tool, rejects empty searches and missing orders, verifies HTTP authentication, and recovers from a simulated HTTP 429 with `Retry-After: 1`. All helper servers stop when it finishes. The final JSON report should show both transports, ten orders, successful spec comparison, and `simulated_429_recovered: true`. GitHub Actions runs these checks on Windows and Ubuntu with Python 3.12 and 3.14 after each push.

On macOS/Linux, use `python3 -m venv .venv`, `.venv/bin/python -m pip install -r requirements.lock`, and `.venv/bin/python` for the same module commands. The container lab was validated using Docker Desktop on Windows; macOS/Linux host provisioning has not been verified locally.

## Connect your own WooCommerce test store

1. In **WooCommerce → Settings → Advanced → REST API → Add key**, choose a dedicated user who can read orders and set permission to **Read**. Generate the consumer key and consumer secret. Existing WordPress user capabilities still apply.
2. Copy `.env.example` to `.env`. Replace the store URL, consumer key, and consumer secret locally. Use the base store URL, such as `https://shop.example`, including a WordPress subdirectory if applicable. Do not append `/wp-json/wc/v3`.
3. Generate a separate HTTP connector token and paste it into `.env` as `MCP_BEARER_TOKEN`:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

Keep `.env` local. Real credentials are not part of this submission. The API secret authenticates the connector to WooCommerce; the separate bearer token authenticates an HTTP client to this connector. They are different credentials and neither belongs in tool arguments.

Start stdio, which an MCP client usually launches as a subprocess:

```powershell
.\.venv\Scripts\python.exe -m wc_connector.server --transport stdio
```

An MCP client's stdio configuration uses the absolute path to the virtual environment's Python executable, arguments `-m wc_connector.server --transport stdio`, the project directory as its working directory, and store settings in its environment or the local project `.env`. stdout is reserved for MCP messages.

For HTTP, start the server in one terminal:

```powershell
.\.venv\Scripts\python.exe -m wc_connector.server --transport http --port 8000
```

It listens at `http://127.0.0.1:8000/mcp`. Configure your MCP client for Streamable HTTP and an `Authorization: Bearer <your locally generated token>` header. Without that header, it returns 401 before processing MCP.

Test either transport with fictional orders already seeded into your test store:

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke --transport stdio --customer-id 101
.\.venv\Scripts\python.exe -m scripts.smoke --transport http --customer-id 101
```

Replace `101` with a known fictional customer's ID; the Docker helper prints the correct ID. HTTP testing requires the HTTP server to be running. The stdio smoke client launches its own server. The smoke client requires at least one order; it is meant for a fictional test store, not a production account.

## Optional real WooCommerce lab

Start Docker Desktop with its Linux engine. From the project folder:

```powershell
.\.venv\Scripts\python.exe test-store\bootstrap.py
```

The helper creates a loopback-only WordPress/WooCommerce store at `https://localhost:8443`, installs WooCommerce 10.2.2, seeds ten fictional orders and three fictional customers, and creates a dedicated Read-only API key. A Caddy proxy issues a local certificate; its CA certificate is copied into `test-store/.secrets/root.crt` and trusted by the connector through `WC_CA_BUNDLE`. TLS verification stays enabled and no machine-wide certificate installation is required. Database passwords and the administrator password are generated locally. Generated API credentials are captured privately and written under ignored `test-store/.secrets/` files. Docker image/plugin downloads require internet access and may take several minutes.

Load that lab's connector settings without displaying their values:

```powershell
.\.venv\Scripts\python.exe -m dotenv -f test-store/.secrets/connector.env run -- .\.venv\Scripts\python.exe -m scripts.smoke --transport stdio --customer-id <printed-customer-id>
```

Replace `<printed-customer-id>` with the integer printed by bootstrap. The real store uses HTTPS because WooCommerce requires it for Basic API-key authentication; the loopback HTTP exception is used only by the simulator. For HTTP MCP, use the same `dotenv ... run --` prefix with `-m wc_connector.server --transport http` in one terminal, then with `-m scripts.smoke --transport http --customer-id <printed-customer-id>` in another. Browsers do not automatically trust the generated local CA; the API demonstration uses its explicit CA file.

The seeder is separate development code with write access to its disposable store. The MCP connector itself never seeds data or gains write permissions. Bootstrap is intended to be rerun on the same lab without creating duplicate orders. Generated credentials also remain in the disposable database for local reruns. These older fixed WordPress/WooCommerce versions are an isolated compatibility lab, not a production deployment recommendation.

Run the complete live-lab verification with one command after bootstrap:

```powershell
.\.venv\Scripts\python.exe -m scripts.live_validate
```

It uses the local lab settings automatically, verifies both MCP transports, reads every page, checks combined/date/text filters and omitted sensitive fields, and confirms invalid store keys and a Read key's write attempt are rejected. The write test targets a nonexistent order with an empty body, so it cannot modify an existing order. This helper accepts only the disposable lab URL and writes a sanitized `LIVE_VALIDATION.json` containing no credentials.

Stop the lab without deleting its data:

```powershell
docker compose --project-directory test-store down
```

## MCP specification and examples

`mcp-tools.json` is an export of runtime `tools/list`, including input/output schemas and read-only annotations. An actual MCP server implements discovery and tool calls; the JSON alone is not a server. Regenerate it after intentionally changing tools:

```powershell
.\.venv\Scripts\python.exe -m scripts.export_spec
```

| Merchant question | Tool call |
| --- | --- |
| Show the first twenty orders | `list_orders({"page": 1, "per_page": 20})` |
| What is the status of order 1001? | `get_order({"order_id": 1001})` |
| Show processing orders for customer 101 | `search_orders({"customer_id": 101, "status": "processing"})` |
| Show orders created in January UTC | `search_orders({"after": "2026-01-01T00:00:00Z", "before": "2026-02-01T00:00:00Z"})` |

These are illustrative calls; IDs in an actual lab are generated by WooCommerce. Tools return structured JSON with a limited order summary. Amounts are decimal strings and dates retain the store's local/GMT fields. Collections return `total`, `total_pages`, and `next_page`; follow pages to browse all orders. The connector does not download the entire store in one call.

## Agent Studio handoff and limits

This is **MCP-compatible**, with protocol-level demonstrations over both supported transports. No Agent Studio account or private connector documentation was available, so **Agent Studio integration has not been verified**. Registering its tool schemas/endpoint and choosing the platform's supported authentication mechanism requires Razorpay's integration requirements. A client that insists on MCP OAuth discovery cannot use this API-key HTTP gate unchanged.

For remote access, use an HTTPS reverse proxy forwarding to this loopback server, restrict allowed hosts/origins, and configure the SDK's host validation for the chosen hostname. The delivered server deliberately has no public bind switch. Shared bearer-token protection is for one merchant and trusted clients; it is not per-user authorization, OAuth, or tenant isolation. No hosted endpoint is part of the submission.

See [CAPABILITIES.md](CAPABILITIES.md), [ARCHITECTURE.md](ARCHITECTURE.md), and [VALIDATION.md](VALIDATION.md) for behavior, failure handling, and exactly what was tested.

## References

- [WooCommerce API-key authentication](https://developer.woocommerce.com/docs/apis/rest-api/authentication/)
- [WooCommerce REST API v3 orders](https://developer.woocommerce.com/docs/apis/rest-api/v3/orders/)
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) — this submission pins the maintained v1 API to `mcp==1.30.0`; do not mix v2 examples with this code.
- [Official WordPress Docker image](https://hub.docker.com/_/wordpress)
