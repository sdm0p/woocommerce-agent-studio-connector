import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    store_url: str
    consumer_key: str
    consumer_secret: str
    allow_local_http: bool = False
    ca_bundle: str | None = None

    def __post_init__(self):
        try:
            url = urlsplit(self.store_url)
            _ = url.port
        except ValueError:
            raise ValueError("WC_STORE_URL is invalid.") from None
        if (not url.hostname or url.username or url.password or url.query or url.fragment
                or url.scheme not in {"https", "http"}):
            raise ValueError("Use a store URL without credentials, query, or fragment.")
        if url.scheme != "https" and not (
            self.allow_local_http and url.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("HTTPS is required except for explicitly enabled loopback testing.")
        if not self.consumer_key or not self.consumer_secret:
            raise ValueError("WC_CONSUMER_KEY and WC_CONSUMER_SECRET are required.")
        if "replace-with" in self.consumer_key or "replace-with" in self.consumer_secret:
            raise ValueError("Replace credential placeholders locally before starting.")
        if self.ca_bundle and not Path(self.ca_bundle).is_file():
            raise ValueError("WC_CA_BUNDLE must point to a readable CA certificate file.")

    @property
    def orders_url(self):
        return self.store_url.rstrip("/") + "/wp-json/wc/v3/orders"

    @classmethod
    def from_env(cls):
        return cls(
            store_url=os.environ.get("WC_STORE_URL", ""),
            consumer_key=os.environ.get("WC_CONSUMER_KEY", ""),
            consumer_secret=os.environ.get("WC_CONSUMER_SECRET", ""),
            allow_local_http=os.environ.get("WC_ALLOW_LOCAL_HTTP", "false").lower() == "true",
            ca_bundle=os.environ.get("WC_CA_BUNDLE") or None,
        )
