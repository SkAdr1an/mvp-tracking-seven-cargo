from urllib.parse import urlsplit, urlunsplit


def canonical_public_origin(value: str) -> str:
    raw = value.strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("PUBLIC_TRIP_BASE_URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("PUBLIC_TRIP_BASE_URL must contain only a public origin")
    path = parsed.path.rstrip("/")
    if path not in {"", "/viagem"} or "://" in parsed.netloc or "://" in path:
        raise ValueError("PUBLIC_TRIP_BASE_URL contains an invalid path or duplicated protocol")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def public_trip_url(base: str, token: str) -> str:
    return f"{canonical_public_origin(base)}/viagem/{token}"
