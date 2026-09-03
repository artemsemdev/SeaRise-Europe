"""Verify the provider-neutral HTTP contract for canonical release objects."""

from __future__ import annotations

import argparse
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Sequence


IMMUTABLE = "public, max-age=31536000, immutable"
EXPOSED = {
    "accept-ranges",
    "cache-control",
    "content-length",
    "content-range",
    "content-type",
    "etag",
}


class HttpDeliveryError(RuntimeError):
    """A canonical object response violates the public delivery contract."""


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


def _request(
    url: str, *, method: str, headers: Mapping[str, str]
) -> Response:
    request = urllib.request.Request(url, method=method, headers=dict(headers))
    try:
        handle = urllib.request.urlopen(request, timeout=15)  # noqa: S310 - explicit URL
    except urllib.error.HTTPError as error:
        handle = error
    with handle:
        return Response(
            status=handle.status,
            headers={key.casefold(): value for key, value in handle.headers.items()},
            body=handle.read(),
        )


def _require(response: Response, name: str, expected: str) -> None:
    actual = response.headers.get(name.casefold())
    if actual != expected:
        raise HttpDeliveryError(f"{name} expected {expected!r}, got {actual!r}")


def _verify_common(
    response: Response, *, origin: str, media_type: str, cache_control: str
) -> tuple[int, str]:
    _require(response, "Access-Control-Allow-Origin", origin)
    _require(response, "Accept-Ranges", "bytes")
    _require(response, "Content-Type", media_type)
    _require(response, "Cache-Control", cache_control)
    exposed = {
        item.strip().casefold()
        for item in response.headers.get("access-control-expose-headers", "").split(",")
        if item.strip()
    }
    if exposed != EXPOSED:
        raise HttpDeliveryError(f"exposed response headers differ: {sorted(exposed)}")
    etag = response.headers.get("etag", "")
    if not re.fullmatch(r'"[a-f0-9]{64}"', etag):
        raise HttpDeliveryError("ETag must be one strong quoted SHA-256")
    length = response.headers.get("content-length", "")
    if not length.isdecimal() or int(length) <= 0:
        raise HttpDeliveryError("Content-Length must be a positive decimal")
    return int(length), etag


def verify_object(
    base_url: str,
    path: str,
    *,
    origin: str,
    denied_origin: str,
    media_type: str,
    cache_control: str,
    versioned: bool = True,
) -> dict[str, object]:
    if versioned and (not path.startswith("/releases/") or ".." in path):
        raise HttpDeliveryError("object path must be a canonical release path")
    if not versioned and path != "/release.json":
        raise HttpDeliveryError("mutable alias path must be exactly /release.json")
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    head = _request(url, method="HEAD", headers={"Origin": origin})
    if head.status != 200 or head.body:
        raise HttpDeliveryError(f"HEAD must return 200 with no body, got {head.status}")
    size, etag = _verify_common(
        head, origin=origin, media_type=media_type, cache_control=cache_control
    )

    full = _request(url, method="GET", headers={"Origin": origin})
    if full.status != 200 or len(full.body) != size:
        raise HttpDeliveryError("canonical GET size/status differs from HEAD")
    full_size, full_etag = _verify_common(
        full, origin=origin, media_type=media_type, cache_control=cache_control
    )
    if full_size != size or full_etag != etag:
        raise HttpDeliveryError("GET and HEAD identity differs")

    end = min(size - 1, 15)
    partial = _request(
        url,
        method="GET",
        headers={"Origin": origin, "Range": f"bytes=1-{end}", "If-Match": etag},
    )
    if partial.status != 206:
        raise HttpDeliveryError(f"range GET must return 206, got {partial.status}")
    _verify_common(
        partial, origin=origin, media_type=media_type, cache_control=cache_control
    )
    _require(partial, "Content-Range", f"bytes 1-{end}/{size}")
    if partial.body != full.body[1 : end + 1]:
        raise HttpDeliveryError("range bytes differ from canonical GET")

    unsatisfied = _request(
        url,
        method="GET",
        headers={"Origin": origin, "Range": f"bytes={size}-"},
    )
    if unsatisfied.status != 416:
        raise HttpDeliveryError("unsatisfied range must return 416")
    _require(unsatisfied, "Content-Range", f"bytes */{size}")
    _require(unsatisfied, "Cache-Control", cache_control)

    denied = _request(url, method="GET", headers={"Origin": denied_origin})
    if "access-control-allow-origin" in denied.headers:
        raise HttpDeliveryError("denied origin received an allow-origin header")

    preflight = _request(
        url,
        method="OPTIONS",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Range, If-Match",
        },
    )
    if preflight.status not in {200, 204}:
        raise HttpDeliveryError("allowed CORS preflight must succeed")
    _require(preflight, "Access-Control-Allow-Origin", origin)
    methods = {
        item.strip() for item in preflight.headers.get("access-control-allow-methods", "").split(",")
    }
    if methods != {"GET", "HEAD"}:
        raise HttpDeliveryError(f"allowed CORS methods differ: {sorted(methods)}")
    request_headers = {
        item.strip().casefold()
        for item in preflight.headers.get("access-control-allow-headers", "").split(",")
    }
    if request_headers != {"if-match", "if-none-match", "range"}:
        raise HttpDeliveryError("allowed CORS request headers differ")
    return {"path": path, "size": size, "etag": etag, "status": "passed"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--denied-origin", default="https://denied.example.invalid")
    parser.add_argument("--pmtiles-path", required=True)
    parser.add_argument("--cog-path", required=True)
    parser.add_argument("--mutable-alias-path", default="/release.json")
    arguments = parser.parse_args(argv)
    try:
        results = [
            verify_object(
                arguments.base_url,
                arguments.pmtiles_path,
                origin=arguments.origin,
                denied_origin=arguments.denied_origin,
                media_type="application/vnd.pmtiles",
                cache_control=IMMUTABLE,
            ),
            verify_object(
                arguments.base_url,
                arguments.cog_path,
                origin=arguments.origin,
                denied_origin=arguments.denied_origin,
                media_type="image/tiff; application=geotiff; profile=cloud-optimized",
                cache_control=IMMUTABLE,
            ),
            verify_object(
                arguments.base_url,
                arguments.mutable_alias_path,
                origin=arguments.origin,
                denied_origin=arguments.denied_origin,
                media_type="application/json",
                cache_control="no-store",
                versioned=False,
            ),
        ]
    except (HttpDeliveryError, OSError) as error:
        print(f"ERROR: {error}")
        return 1
    for result in results:
        print(f"{result['status']}: {result['path']} ({result['size']} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
