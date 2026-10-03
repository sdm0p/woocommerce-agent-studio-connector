import asyncio
import random
import ssl
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from pydantic import ValidationError

from .config import Settings
from .models import OrderPage, OrderSummary


STATUSES = {"pending", "processing", "on-hold", "completed", "cancelled", "refunded", "failed", "trash", "any"}


class ConnectorError(Exception):
    """Only messages constructed locally may cross the tool boundary."""


def positive(value: int, name: str):
    if type(value) is not int or value <= 0:
        raise ConnectorError(f"{name} must be a positive integer.")


def pagination(page: int, per_page: int):
    positive(page, "page")
    positive(per_page, "per_page")
    if per_page > 100:
        raise ConnectorError("per_page must be between 1 and 100.")


def retry_after(value: str | None, now: datetime | None = None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        try:
            return float(value)
        except (ValueError, OverflowError):
            return None
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return max(0.0, (date - (now or datetime.now(timezone.utc))).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return None


def date_filter(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise ConnectorError(f"{name} must be an ISO8601 timestamp with a timezone.") from None


class WooCommerceClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None,
                 sleep=asyncio.sleep, clock=time.monotonic, jitter=random.uniform):
        self.settings, self.http = settings, http
        self.sleep, self.clock, self.jitter = sleep, clock, jitter

    async def _request(self, order_id: int | None = None, params: dict | None = None):
        # Paths and verb are fixed here; no tool can provide a URL or HTTP method.
        url = self.settings.orders_url + (f"/{order_id}" if order_id is not None else "")
        if self.http is None:
            try:
                verify = ssl.create_default_context(cafile=self.settings.ca_bundle) if self.settings.ca_bundle else True
            except (OSError, ssl.SSLError):
                raise ConnectorError("Could not load the configured CA certificate; check WC_CA_BUNDLE.") from None
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=False, verify=verify) as http:
                return await self._retry(http, url, params)
        return await self._retry(self.http, url, params)

    async def _retry(self, http, url, params):
        started = self.clock()
        try:
            async with asyncio.timeout(60):
                for attempt in range(4):
                    response = None
                    try:
                        response = await http.get(
                            url, params=params,
                            auth=httpx.BasicAuth(self.settings.consumer_key, self.settings.consumer_secret),
                            follow_redirects=False, timeout=min(15.0, max(0.01, 60 - (self.clock() - started))),
                        )
                    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                        pass
                    except httpx.HTTPError:
                        raise ConnectorError("Store request failed; check the store configuration.") from None
                    if response is not None:
                        code = response.status_code
                        if code in (401, 403):
                            raise ConnectorError("Store authentication failed; check the key and its Read permission.")
                        if code == 404:
                            raise ConnectorError("Order or store endpoint was not found.")
                        if 200 <= code < 300:
                            try:
                                return response.json(), response.headers
                            except (ValueError, UnicodeError):
                                raise ConnectorError("Store returned an invalid JSON response.") from None
                        if code not in {429, 502, 503, 504}:
                            raise ConnectorError(f"Store request failed (HTTP {code}); check configuration and inputs.")
                    if attempt == 3:
                        raise ConnectorError("Store temporarily unavailable or rate limited; retries exhausted. Try again later.")
                    delay = retry_after(response.headers.get("Retry-After")) if response is not None else None
                    if delay is None:
                        delay = (2 ** attempt) + self.jitter(0, 0.5)
                    if delay >= 60 - (self.clock() - started):
                        raise ConnectorError("Store retry wait exceeds the 60-second budget. Try again later.")
                    await self.sleep(delay)
        except TimeoutError:
            raise ConnectorError("Store request exceeded the 60-second budget. Try again later.") from None

    async def get(self, order_id: int) -> OrderSummary:
        positive(order_id, "order_id")
        data, _ = await self._request(order_id)
        try:
            return OrderSummary.model_validate(data)
        except ValidationError:
            raise ConnectorError("Store returned an unexpected order format.") from None

    async def list(self, page=1, per_page=20, filters: dict | None = None) -> OrderPage:
        pagination(page, per_page)
        params = {"page": page, "per_page": per_page, "orderby": "id", "order": "asc", "context": "view"}
        params.update(filters or {})
        data, headers = await self._request(params=params)
        try:
            if not isinstance(data, list):
                raise ValueError
            total, total_pages = int(headers["X-WP-Total"]), int(headers["X-WP-TotalPages"])
            if total < 0 or total_pages < 0:
                raise ValueError
            orders = [OrderSummary.model_validate(item) for item in data]
            return OrderPage(orders=orders, page=page, per_page=per_page, total=total,
                             total_pages=total_pages, next_page=page + 1 if page < total_pages else None)
        except (ValueError, TypeError, KeyError, ValidationError):
            raise ConnectorError("Store returned an unexpected order or pagination format.") from None

    async def search(self, customer_id=None, status=None, query=None, after=None, before=None,
                     page=1, per_page=20) -> OrderPage:
        filters = {}
        if customer_id is not None:
            positive(customer_id, "customer_id")
            filters["customer"] = customer_id
        if status is not None:
            if status not in STATUSES:
                raise ConnectorError("Unsupported order status.")
            filters["status"] = status
        if query is not None:
            if not isinstance(query, str) or not query.strip() or len(query) > 200:
                raise ConnectorError("query must contain 1–200 characters of search text.")
            filters["search"] = query.strip()
        dates = {}
        for name, value in (("after", after), ("before", before)):
            if value is not None:
                dates[name] = date_filter(value, name)
                filters[name] = dates[name].isoformat().replace("+00:00", "Z")
        if len(dates) == 2 and dates["after"] > dates["before"]:
            raise ConnectorError("after must not be later than before.")
        if dates:
            filters["dates_are_gmt"] = "true"
        if not filters:
            raise ConnectorError("Provide at least one search filter; use list_orders to browse.")
        return await self.list(page, per_page, filters)
