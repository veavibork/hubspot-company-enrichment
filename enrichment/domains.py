from urllib.parse import urlsplit


def normalize_domain(value):
    """"https://www.Acme.com/about" -> "acme.com". Only "www." is stripped; None if not a domain."""
    if not value or not value.strip():
        return None

    text = value.strip().lower()

    # urlsplit only finds the host when a scheme is present.
    if "://" not in text:
        text = "http://" + text

    try:
        host = urlsplit(text).hostname
    except ValueError:
        return None

    if not host:
        return None

    host = host.rstrip(".")
    if host.startswith("www."):
        host = host[4:]

    if "." not in host or " " in host:
        return None

    return host
