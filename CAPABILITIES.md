# What the agent can and cannot do

The connector helps a merchant answer order-status questions without copying data into an AI system by hand.

The agent **can** browse orders a page at a time, read a specific order by ID, and combine filters for customer ID, status, native text search, and creation dates. The output includes order/customer IDs, status, dates, currency, totals, and product line items. It can use this information to summarize which orders need a merchant's attention.

The agent **cannot** create, edit, delete, cancel, or refund an order. It cannot read tickets or inventory, access a second store, fetch arbitrary URLs, supply credentials as tool inputs, or look up a customer by an exact email/name through this connector. Billing/shipping addresses, emails, phone numbers, notes, and custom metadata are omitted. Customer IDs and product names are still merchant data; output minimization is not a guarantee of anonymity.

## Practical limits

- `list_orders` reads one page, with 20 results by default and at most 100. Follow `next_page` until it is null. Pagination is not a consistent snapshot; orders may change between calls.
- `customer_id` means a registered WooCommerce customer ID. Guest orders appear in lists with ID 0 but cannot be isolated with this customer filter.
- `query` delegates to WooCommerce's native order text search. Exact matching and searchable fields depend on the store/version/extensions. The simulator only matches order IDs and does not establish WooCommerce text-search behavior.
- Dates must include a timezone, are converted to UTC, and filter creation dates. The store controls boundary inclusion. Statuses are the standard WooCommerce statuses; custom extension statuses are not supported.
- Read-only credentials still need a WordPress user authorized to read orders. Revoking the key, permissions, or user capabilities causes an authentication error.
- A store, plugin, gateway, or hosting provider may apply its own rate limits. The connector does not assume a universal quota. It waits and retries transient failures, then gives a safe error after three retries or a 60-second request budget. A long required server wait is not shortened to force another request.
- There is no bulk export, cache, background sync, central request queue, or distributed quota coordination. Concurrent agent calls can still encounter rate limits.
- Order/product strings are untrusted external data. An agent should treat them as data, not instructions, and use human review before acting through any other system. This connector provides no action tools.
- Single-store configuration and a shared private HTTP token suit this assignment. Production multi-merchant onboarding, per-user authorization, monitoring, OAuth, and remote deployment require additional work.

No real customer records or working credentials are included. Agent Studio connectivity remains unverified; standard MCP connectivity is demonstrated locally.
