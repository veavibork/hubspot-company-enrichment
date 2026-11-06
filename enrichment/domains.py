import re
from urllib.parse import urlsplit

# Letters, digits and inner hyphens per label; at least two labels. Domains are
# interpolated into SPARQL, so nothing else may get through.
HOSTNAME = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")


def normalize_domain(value):
    """"https://www.Acme.com/about" -> "acme.com". Only "www." is stripped; None if not a valid hostname."""
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

    try:
        host = host.encode("idna").decode("ascii")  # "münchen.de" -> "xn--mnchen-3ya.de"
    except UnicodeError:
        return None

    return host if HOSTNAME.match(host) else None
