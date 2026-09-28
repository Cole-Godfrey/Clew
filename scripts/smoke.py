"""Verify a deployed ShortURL instance through its public HTTP API."""

import argparse
import json
import os
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def request(base_url: str, method: str, path: str, key: str | None = None, body: dict | None = None):
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if key is not None:
        headers["X-API-Key"] = key
    payload = json.dumps(body).encode() if body is not None else None
    outgoing = Request(f"{base_url}{path}", data=payload, headers=headers, method=method)
    opener = build_opener(NoRedirect())
    try:
        incoming = opener.open(outgoing, timeout=15)
    except HTTPError as error:
        incoming = error
    with incoming:
        return (
            incoming.status,
            {name.lower(): value for name, value in incoming.headers.items()},
            incoming.read(),
        )


def expect_status(result, expected: int) -> None:
    if result[0] != expected:
        raise SystemExit(f"Expected HTTP {expected}, got {result[0]}: {result[2][:300]!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a deployed ShortURL instance")
    parser.add_argument("base_url", help="Public origin, such as https://name.pythonanywhere.com")
    parser.add_argument(
        "--destination", default="https://github.com/Cole-Godfrey/shorturl", help="URL to shorten"
    )
    args = parser.parse_args()
    key = os.getenv("SHORTURL_API_KEY")
    if not key:
        raise SystemExit("Set SHORTURL_API_KEY in the environment")
    base_url = args.base_url.rstrip("/")
    try:
        origin = urlsplit(base_url)
        origin.port
    except ValueError as exc:
        raise SystemExit("base_url is invalid") from exc
    local = origin.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        not origin.hostname
        or (origin.scheme != "https" and not (local and origin.scheme == "http"))
        or origin.username is not None
        or origin.password is not None
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise SystemExit("base_url must be a public HTTPS origin or local HTTP origin")

    expect_status(request(base_url, "GET", "/healthz"), 200)
    created = request(base_url, "POST", "/api/links", key, {"url": args.destination})
    expect_status(created, 201)
    link = json.loads(created[2])
    redirected = request(base_url, "GET", f"/{link['code']}")
    expect_status(redirected, 302)
    if redirected[1].get("location") != args.destination:
        raise SystemExit("Redirect destination did not match")
    stats_response = request(base_url, "GET", f"/api/links/{link['code']}/stats", key)
    expect_status(stats_response, 200)
    stats = json.loads(stats_response[2])
    if stats["click_count"] != 1 or not stats["last_clicked_at"]:
        raise SystemExit("Click analytics did not update")
    print(link["short_url"])


if __name__ == "__main__":
    main()
