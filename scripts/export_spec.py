import asyncio
import json
from pathlib import Path

from wc_connector.config import Settings
from wc_connector.server import create_server


async def main():
    # Discovery is local and never contacts this reserved example domain.
    server = create_server(Settings("https://example.invalid", "placeholder", "placeholder"))
    tools = await server.list_tools()
    spec = {"name": "woocommerce-readonly-orders", "transports": ["stdio", "streamable-http"],
            "tools": [t.model_dump(mode="json", exclude_none=True) for t in tools]}
    path = Path(__file__).resolve().parents[1] / "mcp-tools.json"
    path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
