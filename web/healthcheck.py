#!/usr/bin/env python3
"""Check the web listener using its configured local origin when required."""
import http.client
import os
from urllib.parse import urlsplit


def main():
    headers = {}
    if os.environ.get("CLUSTERWEAVE_ACCESS_PROFILE") == "local-owner":
        headers["Host"] = urlsplit(os.environ.get("CLUSTERWEAVE_PUBLIC_BASE_URL", "")).netloc
    connection = http.client.HTTPConnection("127.0.0.1", int(os.environ.get("PORT", "8080")), timeout=5)
    try:
        connection.request("GET", "/", headers=headers)
        return 0 if connection.getresponse().status == 200 else 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
