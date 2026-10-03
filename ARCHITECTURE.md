# Architecture and design choices

```text
MCP agent/client
    │ stdio (local process) OR Streamable HTTP /mcp (bearer-token gate)
    ▼
Official MCP SDK → input validation → three read-only tool functions
    ▼
WooCommerce client → fixed GET orders endpoints → retry policy
    │ Basic auth header containing the merchant's Read-only API key pair
    ▼
WooCommerce REST API v3 → field allowlist → structured order summaries
```

## Authentication and boundaries

Store settings are read from the environment or a local `.env`. HTTPS is required; a flag permits HTTP only to `localhost`, `127.0.0.1`, or `::1` for the simulator. TLS certificate verification stays enabled. The optional `WC_CA_BUNDLE` points to a trusted CA PEM file for the HTTPS test store. Redirects are not followed, so keys cannot be forwarded to a redirected host. The merchant controls the configured store URL; an agent cannot replace it through tool inputs.

The SDK exposes only `list_orders`, `get_order`, and `search_orders`. Their schemas constrain IDs, pagination, and statuses. Additional arguments are rejected. A custom SDK subclass sanitizes argument errors so supplied values are not echoed. Domain validation handles search requirements and timezone-aware dates. SDK tool annotations describe read-only behavior; actual enforcement comes from the fixed GET implementation and the store's Read-scoped key.

For HTTP, ASGI middleware performs a constant-time comparison of a separate bearer token and rejects missing, wrong, or duplicate authorization headers. The middleware forwards lifespan events to the SDK, preserving HTTP session-manager startup. This is private API-key authentication, not a standards-complete MCP OAuth server. stdio relies on the local process boundary and needs no HTTP token.

## Data and failure handling

The client calls only `/wp-json/wc/v3/orders` or `/wp-json/wc/v3/orders/{integer_id}`. Each operation uses an async HTTP client with a 15-second per-attempt timeout and a 60-second overall budget. HTTP 429, 502, 503, 504 and transient connection/read/protocol failures can retry. Authentication, missing-order, redirects, and other HTTP failures do not retry.

Retry-After accepts integer seconds or an HTTP date. Missing/malformed values use 1, 2, then 4 seconds plus 0–0.5 seconds jitter. A delay that consumes the remaining budget returns a retryable error rather than retrying earlier than the server requested. Cancellation from the client propagates normally.

Results pass through typed field allowlists before reaching the MCP client. Monetary strings are preserved without float conversion. Native pagination headers supply totals and the next page. Unexpected JSON, missing headers, and invalid result formats produce locally constructed error messages; upstream bodies, credential values, and exception details are not forwarded. HTTP access logging and HTTP-client informational logging are disabled in the connector entrypoint.

## Demonstration and portability

The simulator implements the small WooCommerce surface needed for the fictional demonstration and checks real Basic authentication headers. The smoke client uses the SDK's MCP initialization, discovery, and call protocol. Runtime discovery is compared directly with the exported specification.

The optional Docker lab provisions an actual WordPress/WooCommerce store and real Read-scoped API keys. Caddy provides local HTTPS so WooCommerce's standard Basic API-key authentication remains usable. WordPress recognizes the trusted internal proxy's forwarded HTTPS header; its container port is not exposed to the host. The connector explicitly trusts Caddy's generated CA. The seeder uses write access only during isolated lab setup and is never reachable as an MCP tool. Container versions are a lab compatibility target, not immutable image digests. The recipe and both transports were executed successfully on Docker Desktop; live key failures, pagination, and search were also verified.

Dependency versions, including transitive dependencies, are fixed in `requirements.lock` with platform markers. Run the project from its root for the documented module commands. `pyproject.toml` also defines an installable production package and `wc-mcp` entrypoint; development helpers are run from source.
