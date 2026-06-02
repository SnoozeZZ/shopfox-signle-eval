"""
URL normalization for link-set comparison (KR4-5 and future metrics).
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PREFIXES = (
    "utm_",
    "ref",
    "tag",
    "pf_rd_",
    "pd_rd_",
    "qid",
    "sprefix",
    "crid",
    "dib",
    "keywords",
    "psc",
    "smid",
)


def _is_tracking_param(key: str) -> bool:
    lower = key.lower()
    return any(lower == p or lower.startswith(p) for p in _TRACKING_PREFIXES)


def normalize_url(url: str) -> str | None:
    """Canonical form for set intersection; returns None if not a valid http(s) URL."""
    raw = str(url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        port = parsed.port
        if port and (
            (parsed.scheme == "http" and port != 80)
            or (parsed.scheme == "https" and port != 443)
        ):
            netloc = f"{host}:{port}"
        else:
            netloc = host

        path = parsed.path or ""
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        query_pairs = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if not _is_tracking_param(k)
        ]
        query = urlencode(sorted(query_pairs))

        return urlunparse((parsed.scheme.lower(), netloc, path, "", query, ""))
    except Exception:
        return None
