"""Domain normalization, so the same company always produces the same key."""

from urllib.parse import urlsplit


def normalize_domain(value):
    """Reduce a website or domain to a bare, lowercase hostname.

    "https://www.Acme.com/about?x=1" -> "acme.com"

    Only a leading "www." is stripped. Other subdomains (e.g. "shop.acme.com")
    are kept, because telling a subdomain from a registrable domain
    ("acme.co.uk") correctly requires the Public Suffix List.

    Returns None when the value can't be a domain.
    """
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
