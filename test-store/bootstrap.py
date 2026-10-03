"""Provision a disposable local WooCommerce lab; never target a real merchant store."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

LAB = Path(__file__).resolve().parent
ROOT = LAB.parent


def main():
    ready = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if ready.returncode:
        raise SystemExit("Start Docker Desktop's Linux engine, then run this helper again.")
    (LAB / ".secrets").mkdir(exist_ok=True)
    os.chmod(LAB / ".secrets", 0o700)
    local_env = LAB / ".env"
    if not local_env.exists():
        values = {name: secrets.token_hex(32) for name in ("DB_PASSWORD", "DB_ROOT_PASSWORD", "WP_ADMIN_PASSWORD")}
        local_env.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
        os.chmod(local_env, 0o600)
    # The existing connector .env is never overwritten by this provisioning helper.
    subprocess.run(["docker", "compose", "up", "-d", "wordpress", "proxy"], cwd=LAB, check=True)
    ca_file = LAB / ".secrets/root.crt"
    for _ in range(60):
        copy = subprocess.run(["docker", "compose", "cp", "proxy:/data/caddy/pki/authorities/local/root.crt",
                               str(ca_file)], cwd=LAB, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if copy.returncode == 0:
            break
        time.sleep(1)
    else:
        raise SystemExit("Local HTTPS certificate was not initialized. Check the proxy container.")
    provision = subprocess.run(["docker", "compose", "run", "--rm", "wpcli", "/bootstrap/setup.sh"],
                               cwd=LAB, capture_output=True, text=True)
    if provision.returncode:
        raise SystemExit("Lab provisioning failed. Check container readiness, image availability, and plugin download access. No credentials were printed.")
    marker = "_WC_LAB_RESULT_"
    payload = next((line[len(marker):] for line in provision.stdout.splitlines() if line.startswith(marker)), None)
    if payload is None:
        raise SystemExit("Lab provisioning returned no credential result.")
    credentials = json.loads(payload)
    credential_path = LAB / ".secrets/connector.json"
    credential_path.write_text(json.dumps(credentials, indent=2), encoding="utf-8")
    os.chmod(credential_path, 0o600)
    generated = LAB / ".secrets/connector.env"
    if not generated.exists():
        values = {"WC_STORE_URL": "https://localhost:8443", "WC_ALLOW_LOCAL_HTTP": "false",
                  "WC_CA_BUNDLE": ca_file.as_posix(),
                  "WC_CONSUMER_KEY": credentials["consumer_key"], "WC_CONSUMER_SECRET": credentials["consumer_secret"],
                  "MCP_BEARER_TOKEN": secrets.token_urlsafe(32)}
        generated.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
        os.chmod(generated, 0o600)
    print("Local lab ready at https://localhost:8443; credentials remain in ignored local files.")
    print("Load test-store/.secrets/connector.env locally to use the connector.")
    print("Smoke-test customer ID:", credentials["customer_ids"][0])


if __name__ == "__main__":
    main()
