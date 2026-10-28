import ipaddress
import socket
from urllib.parse import urlparse

from app.common import get_logger
logger = get_logger()


def is_public_http_url(url: str) -> bool:
    """only http(s) urls whose host resolves to public addresses. keeps the hub from fetching
    localhost, the docker network or the lan on behalf of the model (SSRF)"""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
    except (ValueError, socket.gaierror, UnicodeError) as e:
        logger.warning(f"fetch_url: can't resolve {url}: {repr(e)}")
        return False

    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])     # strip an ipv6 zone id
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            logger.warning(f"fetch_url: {url} resolves to non public address {ip}")
            return False
    return bool(infos)
