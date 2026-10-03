"""Fictional WooCommerce-compatible API. It is NOT a real WooCommerce store."""
import base64
import copy
import hmac
import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


def fictional_orders():
    statuses = ["processing", "completed", "pending", "on-hold", "failed"]
    return [{
        "id": 1001 + i, "customer_id": 101 + i % 3 if i != 9 else 0,
        "status": statuses[i % 5], "currency": "INR", "total": "499.00", "total_tax": "0.00",
        "shipping_total": "0.00", "discount_total": "0.00",
        "date_created": f"2026-01-{i+1:02d}T12:00:00",
        "date_modified": f"2026-01-{i+1:02d}T12:00:00",
        "date_created_gmt": f"2026-01-{i+1:02d}T12:00:00",
        "date_modified_gmt": f"2026-01-{i+1:02d}T12:00:00",
        "line_items": [{"product_id": 201, "name": "Fictional cotton T-shirt", "quantity": 1,
                        "subtotal": "499.00", "total": "499.00", "meta_data": [{"secret": "discard"}]}],
        "billing": {"email": f"fictional{i}@example.invalid", "phone": "FICTIONAL", "address_1": "FICTIONAL"},
        "customer_note": "Untrusted order note; never expose this.",
        "meta_data": [{"key": "private", "value": "must-not-be-returned"}],
    } for i in range(10)]


class Simulator:
    def __init__(self, key: str, secret: str, rate_limit_once=True):
        self.expected = "Basic " + base64.b64encode(f"{key}:{secret}".encode()).decode()
        self.orders = fictional_orders()
        self.rate_limit_once = rate_limit_once
        self.rate_limits = 0
        self.requests = []
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def respond(self, code, data, headers=None):
                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, str(v))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if not hmac.compare_digest(self.headers.get("Authorization", ""), owner.expected):
                    return self.respond(401, {"code": "woocommerce_rest_authentication_error"})
                url = urlsplit(self.path)
                base = "/wp-json/wc/v3/orders"
                with owner.lock:
                    owner.requests.append(("GET", url.path))
                    if owner.rate_limit_once and url.path == base:
                        owner.rate_limit_once = False
                        owner.rate_limits += 1
                        return self.respond(429, {"code": "rate_limited"}, {"Retry-After": "1"})
                if url.path.startswith(base + "/"):
                    try:
                        order_id = int(url.path.removeprefix(base + "/"))
                    except ValueError:
                        return self.respond(404, {})
                    order = next((item for item in owner.orders if item["id"] == order_id), None)
                    return self.respond(200, order) if order else self.respond(404, {})
                if url.path != base:
                    return self.respond(404, {})
                params = {k: v[0] for k, v in parse_qs(url.query).items()}
                orders = copy.deepcopy(owner.orders)
                if "customer" in params:
                    orders = [o for o in orders if o["customer_id"] == int(params["customer"])]
                if params.get("status", "any") != "any":
                    orders = [o for o in orders if o["status"] == params["status"]]
                if "search" in params:
                    # Intentionally limited simulator search, not WooCommerce search semantics.
                    orders = [o for o in orders if params["search"].lower() in str(o["id"])]
                for name in ("after", "before"):
                    if name in params:
                        from datetime import datetime, timezone
                        threshold = datetime.fromisoformat(params[name].replace("Z", "+00:00"))
                        def keep(o):
                            date = datetime.fromisoformat(o["date_created_gmt"]).replace(tzinfo=timezone.utc)
                            return date > threshold if name == "after" else date < threshold
                        orders = [o for o in orders if keep(o)]
                page, size = int(params.get("page", "1")), int(params.get("per_page", "20"))
                total = len(orders)
                return self.respond(200, orders[(page-1)*size:page*size],
                                    {"X-WP-Total": total, "X-WP-TotalPages": math.ceil(total/size)})

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.http.server_port}"

    def __enter__(self):
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=5)
