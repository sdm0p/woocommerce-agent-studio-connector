import base64
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx
import pytest

from scripts.simulator import fictional_orders
from wc_connector.client import ConnectorError, WooCommerceClient, retry_after
from wc_connector.config import Settings

SETTINGS = Settings("https://example.invalid/shop", "test-consumer-key", "test-consumer-secret")
ORDER = fictional_orders()[0]


def response(code=200, data=None, headers=None):
    return httpx.Response(code, json=ORDER if data is None else data, headers=headers)


async def test_auth_get_and_sensitive_field_exclusion():
    seen = []
    def handle(request):
        seen.append(request)
        return response()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        order = await WooCommerceClient(SETTINGS, http).get(1001)
    request = seen[0]
    assert request.method == "GET"
    assert str(request.url) == "https://example.invalid/shop/wp-json/wc/v3/orders/1001"
    expected = base64.b64encode(b"test-consumer-key:test-consumer-secret").decode()
    assert request.headers["authorization"] == "Basic " + expected
    dumped = order.model_dump_json()
    for field in ("billing", "email", "phone", "address_1", "customer_note", "meta_data", "private", "discard"):
        assert field not in dumped


async def test_combined_filters_and_pagination():
    seen = []
    def handle(request):
        seen.append(request)
        return response(data=[ORDER], headers={"X-WP-Total": "3", "X-WP-TotalPages": "3"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        page = await WooCommerceClient(SETTINGS, http).search(
            customer_id=101, status="processing", query="  1001  ",
            after="2026-01-01T05:30:00+05:30", before="2026-02-01T00:00:00Z", page=2, per_page=1)
    assert dict(seen[0].url.params) == {
        "page": "2", "per_page": "1", "orderby": "id", "order": "asc", "context": "view",
        "customer": "101", "status": "processing", "search": "1001",
        "after": "2026-01-01T00:00:00Z", "before": "2026-02-01T00:00:00Z", "dates_are_gmt": "true"}
    assert page.next_page == 3 and page.total == 3


async def test_empty_page():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: response(data=[], headers={"X-WP-Total": "0", "X-WP-TotalPages": "0"}))) as http:
        page = await WooCommerceClient(SETTINGS, http).list()
    assert page.orders == [] and page.next_page is None


@pytest.mark.parametrize("code", [400, 401, 403, 404, 500, 301])
async def test_nonretryable_errors_sanitized(code):
    calls = []
    def handle(request):
        calls.append(request)
        return response(code, data={"secret": "do-not-leak"}, headers={"Location": "https://other.invalid"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(ConnectorError) as caught:
            await WooCommerceClient(SETTINGS, http).get(1001)
    assert len(calls) == 1
    assert "do-not-leak" not in str(caught.value)
    assert SETTINGS.consumer_secret not in str(caught.value)


@pytest.mark.parametrize("code", [429, 502, 503, 504])
async def test_retry_exhaustion_four_attempts(code):
    calls, sleeps = [], []
    def handle(request):
        calls.append(request)
        return response(code)
    async def sleep(delay):
        sleeps.append(delay)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(ConnectorError, match="retries exhausted"):
            await WooCommerceClient(SETTINGS, http, sleep=sleep, jitter=lambda *_: 0).get(1001)
    assert len(calls) == 4 and sleeps == [1, 2, 4]


@pytest.mark.parametrize("header,expected", [("2", 2), ("0", 0), (None, 1.25), ("garbage", 1.25), ("-1", 1.25)])
async def test_retry_after_and_fallback(header, expected):
    calls, sleeps = [], []
    def handle(request):
        calls.append(request)
        return response(429, headers={"Retry-After": header} if header is not None else {}) if len(calls) == 1 else response()
    async def sleep(delay):
        sleeps.append(delay)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        await WooCommerceClient(SETTINGS, http, sleep=sleep, jitter=lambda *_: .25).get(1001)
    assert sleeps == [expected] and len(calls) == 2


def test_retry_after_http_date():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert retry_after(format_datetime(now.replace(second=5)), now) == 5
    assert retry_after(format_datetime(now), now.replace(second=10)) == 0


async def test_long_retry_wait_rejected_without_sleep():
    calls = []
    def handle(request):
        calls.append(request)
        return response(429, headers={"Retry-After": "120"})
    async def sleep(_):
        pytest.fail("Must not shorten the server's required wait")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(ConnectorError, match="budget"):
            await WooCommerceClient(SETTINGS, http, sleep=sleep).get(1001)
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError])
async def test_transient_network_retry(failure):
    calls = []
    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            raise failure("sensitive upstream message", request=request)
        return response()
    async def sleep(_):
        pass
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await WooCommerceClient(SETTINGS, http, sleep=sleep).get(1001)
    assert result.id == 1001 and len(calls) == 2


@pytest.mark.parametrize("kwargs", [{}, {"customer_id": 0}, {"status": "wrong"}, {"query": " "},
    {"query": "x"*201}, {"after": "2026-01-01"}, {"before": "invalid"},
    {"after": "2026-02-01T00:00:00Z", "before": "2026-01-01T00:00:00Z"},
    {"status": "processing", "per_page": 101}, {"status": "processing", "page": True}])
async def test_invalid_search_never_contacts_store(kwargs):
    def handle(_):
        pytest.fail("Invalid inputs must not contact WooCommerce")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(ConnectorError):
            await WooCommerceClient(SETTINGS, http).search(**kwargs)


@pytest.mark.parametrize("data,headers", [({"wrong": "sensitive"}, {}),
    ([{"id": 1, "billing": "sensitive"}], {"X-WP-Total": "1", "X-WP-TotalPages": "1"}),
    ([], {"X-WP-Total": "bad", "X-WP-TotalPages": "1"})])
async def test_malformed_upstream_result_sanitized(data, headers):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response(data=data, headers=headers))) as http:
        with pytest.raises(ConnectorError) as caught:
            await WooCommerceClient(SETTINGS, http).list()
    assert "sensitive" not in str(caught.value)


@pytest.mark.parametrize("url,allow", [("http://remote.example", True), ("http://localhost", False),
    ("https://user:password@example.invalid", False), ("https://example.invalid?key=secret", False),
    ("https://example.invalid#fragment", False), ("file:///tmp/orders", False)])
def test_unsafe_store_urls(url, allow):
    with pytest.raises(ValueError):
        Settings(url, "key", "secret", allow)


def test_explicit_loopback_exception():
    assert Settings("http://127.0.0.1:8080", "key", "secret", True).orders_url.endswith("/orders")


def test_missing_ca_file_rejected(tmp_path):
    with pytest.raises(ValueError, match="WC_CA_BUNDLE"):
        Settings("https://localhost:8443", "key", "secret", ca_bundle=str(tmp_path / "missing.pem"))


async def test_invalid_ca_file_sanitized(tmp_path):
    ca = tmp_path / "bad.pem"
    ca.write_text("not a certificate; sensitive content")
    settings = Settings("https://localhost:8443", "key", "secret", ca_bundle=str(ca))
    with pytest.raises(ConnectorError, match="CA certificate") as caught:
        await WooCommerceClient(settings).get(1)
    assert "sensitive" not in str(caught.value)


async def test_http_date_retry_used_by_request():
    from datetime import timedelta
    calls, sleeps = [], []
    date = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=10))
    def handle(request):
        calls.append(request)
        return response(429, headers={"Retry-After": date}) if len(calls) == 1 else response()
    async def sleep(delay):
        sleeps.append(delay)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        await WooCommerceClient(SETTINGS, http, sleep=sleep).get(1001)
    assert len(calls) == 2 and len(sleeps) == 1 and 8 <= sleeps[0] <= 10


async def test_elapsed_time_reduces_retry_budget():
    calls = []
    elapsed = iter([0, 0, 59.5])
    def handle(request):
        calls.append(request)
        return response(429, headers={"Retry-After": "1"})
    async def sleep(_):
        pytest.fail("Must account for elapsed request time before retrying")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(ConnectorError, match="budget"):
            await WooCommerceClient(SETTINGS, http, sleep=sleep, clock=lambda: next(elapsed)).get(1001)
    assert len(calls) == 1


async def test_non_json_response_sanitized():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, text="<html>sensitive upstream content</html>"))) as http:
        with pytest.raises(ConnectorError, match="invalid JSON") as caught:
            await WooCommerceClient(SETTINGS, http).get(1)
    assert "sensitive" not in str(caught.value)


async def test_invalid_order_result_sanitized():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: response(data={"billing": "sensitive upstream content"}))) as http:
        with pytest.raises(ConnectorError, match="unexpected order") as caught:
            await WooCommerceClient(SETTINGS, http).get(1)
    assert "sensitive" not in str(caught.value)
