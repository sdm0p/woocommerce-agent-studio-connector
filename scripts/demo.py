"""Self-contained real MCP client/server demonstration using only fictional data."""
import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys

import httpx

from scripts.simulator import Simulator
from scripts.smoke import ROOT, connect, exercise


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def main():
    # Runtime-only secrets are never printed or written to the submission.
    key, secret, token = (secrets.token_urlsafe(32) for _ in range(3))
    with Simulator(key, secret) as simulator:
        env = dict(os.environ, WC_STORE_URL=simulator.url, WC_CONSUMER_KEY=key,
                   WC_CONSUMER_SECRET=secret, WC_ALLOW_LOCAL_HTTP="true", MCP_BEARER_TOKEN=token, WC_CA_BUNDLE="")
        async with connect(env=env) as session:
            stdio = await exercise(session)
        port = unused_port()
        url = f"http://127.0.0.1:{port}/mcp"
        process = subprocess.Popen([sys.executable, "-m", "wc_connector.server", "--transport", "http",
                                    "--port", str(port)], cwd=ROOT, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            async with httpx.AsyncClient(timeout=1) as http:
                for _ in range(150):
                    if process.poll() is not None:
                        raise RuntimeError("HTTP MCP server exited before it was ready")
                    try:
                        response = await http.post(url, json={})
                        if response.status_code == 401:
                            break
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(0.1)
                else:
                    raise RuntimeError("HTTP MCP server did not start in time")
                wrong = await http.post(url, headers={"Authorization": "Bearer incorrect"}, json={})
                if wrong.status_code != 401:
                    raise AssertionError("Incorrect HTTP bearer token was accepted")
            async with connect("http", url, env) as session:
                remote = await exercise(session)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if simulator.rate_limits != 1:
            raise AssertionError("Rate-limit demonstration was not exercised")
        report = {"dataset": "10 fictional orders; WooCommerce API simulator, not live WooCommerce",
                  "stdio": stdio, "http": remote, "missing_and_wrong_http_tokens_rejected": True,
                  "simulated_429_recovered": True, "upstream_requests": len(simulator.requests),
                  "upstream_methods": sorted({method for method, _ in simulator.requests})}
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
