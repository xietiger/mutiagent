from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

from app.urls import validate_loopback_url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m app.http_exec URL", file=sys.stderr)
        sys.exit(2)
    try:
        url = validate_loopback_url(sys.argv[1])
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    body = sys.stdin.buffer.read()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=60) as response:
            sys.stdout.buffer.write(response.read())
    except Exception as exc:
        sys.stdout.write(json.dumps({"error": type(exc).__name__}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
