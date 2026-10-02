import json
import os
import tempfile
import time
from pathlib import Path

from mitmproxy import http

TARGET_DOMAINS = tuple(
    item.strip().lower().lstrip(".")
    for item in os.environ.get("TARGET_DOMAINS", "").split(",")
    if item.strip()
)
OUTPUT = Path(os.environ.get("COOKIE_FILE", "/data/latest-cookie.json"))


def matches(host):
    host = host.lower().rstrip(".")
    return bool(TARGET_DOMAINS) and any(host == domain or host.endswith("." + domain) for domain in TARGET_DOMAINS)


def request(flow: http.HTTPFlow):
    host = flow.request.pretty_host
    cookie = flow.request.headers.get("cookie")
    if not cookie or not matches(host):
        return
    value = {"cookie": cookie, "host": host, "url": flow.request.pretty_url, "updated_at": time.time()}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="cookie-", dir=str(OUTPUT.parent))
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.write("\n")
        os.replace(name, OUTPUT)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
