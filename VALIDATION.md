# Validation record

Validated on Windows on **3 October 2026**. This record distinguishes simulator evidence from real platform evidence.

| Check | Result |
| --- | --- |
| Automated client/config/MCP tests | 60 passed on Python 3.12.2 and Python 3.14.4 |
| Docker Compose configuration and provisioning | Passed; Docker Engine 29.5.3 on Windows Docker Desktop |
| Original extracted source package | 60 tests and both transport demos passed; no local credential files or API-key literals |
| Real MCP stdio initialization, tool discovery, and calls | Passed against fictional WooCommerce API simulator |
| Real MCP Streamable HTTP initialization, discovery, and calls | Passed against fictional WooCommerce API simulator |
| Runtime tool schemas match exported specification | Passed |
| Missing/wrong HTTP bearer token rejected | Passed; duplicate-header rejection also unit tested |
| Simulator HTTP 429 followed by successful retry | Passed with `Retry-After: 1` |
| All simulator upstream methods | GET only; nine authenticated requests across the demo |
| Live WooCommerce | Passed against WooCommerce 10.2.2 / WordPress 6.8.3 with ten fictional orders |
| Live WooCommerce through both MCP transports | Passed: initialization, discovery, list/get/search, invalid search, missing order |
| HTTPS certificate verification | Passed using the generated local CA, without disabling verification |
| Live pagination and filters | Passed: ten distinct orders over four pages, combined customer/status, January dates, native order-ID text search, empty search |
| Invalid WooCommerce credentials / Read key attempting write | Both rejected with HTTP 401 |
| Razorpay Agent Studio | Pending — no access or private integration documentation |

Tests cover authentication headers, safe configured URLs, sensitive-field exclusion, combined filters and UTC conversion, pagination, empty results, malformed responses, invalid MCP inputs, unknown tools, non-retryable errors, Retry-After parsing/fallback and HTTP-date use, retry exhaustion, elapsed-time budgets, long required waits, transient network errors, CA-file validation, and bearer-token validation. Retry sleeps are injected in unit tests to avoid unnecessary waiting. The end-to-end demo uses a real one-second delay. The restricted development environment required directing pytest's temporary files into the workspace; ordinary local runs can use the default temporary directory.

## Reproduce

From the project root after installing `requirements.lock`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.demo
```

For real WooCommerce evidence, start Docker Desktop and run:

```powershell
.\.venv\Scripts\python.exe test-store/bootstrap.py
.\.venv\Scripts\python.exe -m scripts.live_validate
```

[LIVE_VALIDATION.json](LIVE_VALIDATION.json) records the sanitized successful live result. The read-scope enforcement test makes a direct development HTTP request to a nonexistent order; it is not an MCP tool and cannot modify an existing order. The agent-facing connector's upstream operations remain GET only.

Rate-limit recovery is covered by controlled simulator/unit-test responses; the live WooCommerce lab did not return HTTP 429 during validation. Agent Studio is the remaining external limitation. Its supported connector setup must be verified when Razorpay platform access or private integration documentation becomes available.
