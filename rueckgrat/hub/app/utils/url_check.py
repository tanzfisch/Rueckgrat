"""SSRF guard for everything the hub fetches on behalf of the model (fetch_url, websearch pages, the browser).

check_url resolves the host and checks every address. fetch then connects to exactly the checked address
(Host header and TLS SNI/certificate stay the real host name), so a DNS answer that changes between check and
connect (DNS rebinding) can't redirect the request. redirects are followed by hand, each Location is checked
the same way, at most MAX_REDIRECTS.

Default: public internet only, no private, LAN, loopback, link-local or cloud metadata addresses.
HUB_FETCH_ALLOW (rueckgrat/.env, needs a hub rebuild) opens local targets, comma separated:
  - a CIDR or address:  192.168.2.0/24, 127.0.0.1, fd00::/8
  - a host name:        nas.local   (exact name, whatever it resolves to)
  - private:            all private/LAN ranges (10/8, 172.16/12 incl. the docker networks, 192.168/16,
                        100.64/10, fc00::/7). not loopback, not link-local
Cloud metadata (169.254.169.254, fd00:ec2::254) stays blocked unless that exact address is listed.
"""
import ipaddress
import os
import socket
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional
from urllib.parse import urlparse, urljoin

import certifi
import urllib3

from app.common import get_logger
logger = get_logger()

MAX_REDIRECTS = 5
MAX_BYTES = 10 * 1024 * 1024    # a page, not a download
METADATA_IPS = {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254")}
PRIVATE_NETS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")]
REDIRECT_STATUS = {301, 302, 303, 307, 308}


class FetchBlocked(Exception):
    """the url is not allowed. str() is a message for the model/user, e.g. 'blocked: private address ...'"""


@dataclass
class FetchPolicy:
    nets: list = field(default_factory=list)        # listed CIDRs/addresses
    hosts: set = field(default_factory=set)         # listed host names
    private: bool = False

    def allows(self, ip, hostname: str) -> Optional[str]:
        """None if the address may be fetched, else the reason it is blocked"""
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip in METADATA_IPS:
            # only an exact listing, a wider range or a listed name is not enough
            if any(n.num_addresses == 1 and ip in n for n in self.nets):
                return None
            return f"blocked: cloud metadata address {ip}, not in HUB_FETCH_ALLOW"
        if any(ip in n for n in self.nets) or hostname in self.hosts:
            return None
        if ip.is_global and not ip.is_multicast:
            return None
        if self.private and any(ip in n for n in PRIVATE_NETS):
            return None
        kind = "loopback" if ip.is_loopback else "link-local" if ip.is_link_local else "private" if ip.is_private else "non public"
        return f"blocked: {kind} address {ip}, not in HUB_FETCH_ALLOW"


@lru_cache(maxsize=4)
def _parse_policy(value: str) -> FetchPolicy:
    policy = FetchPolicy()
    for item in (part.strip() for part in value.split(",")):
        if not item:
            continue
        if item.lower() == "private":
            policy.private = True
            continue
        try:
            policy.nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            policy.hosts.add(item.lower().rstrip("."))
    return policy


def fetch_policy() -> FetchPolicy:
    return _parse_policy(os.environ.get("HUB_FETCH_ALLOW", ""))


def _resolve(hostname: str, port: int) -> list:
    infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    ips = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])     # strip an ipv6 zone id
        if ip not in ips:
            ips.append(ip)
    return ips


def check_url(url: str) -> tuple:
    """(parsed url, port, checked addresses) or FetchBlocked. every address the name resolves to must be
    allowed: with a mix, the connection could end up on any of them"""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise FetchBlocked(f"blocked: only http(s) urls, not '{url}'")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        hostname = parsed.hostname.lower().rstrip(".")
        ips = _resolve(hostname, port)
    except FetchBlocked:
        raise
    except (ValueError, socket.gaierror, UnicodeError) as e:
        logger.debug(f"fetch: can't resolve {url}: {repr(e)}")
        raise FetchBlocked(f"can't resolve the host of '{url}'")
    if not ips:
        raise FetchBlocked(f"can't resolve the host of '{url}'")
    policy = fetch_policy()
    for ip in ips:
        reason = policy.allows(ip, hostname)
        if reason:
            logger.debug(f"fetch {url}: {reason}")
            raise FetchBlocked(reason)
    return parsed, port, ips


def is_public_http_url(url: str) -> bool:
    """True if url may be fetched (public, or opened by HUB_FETCH_ALLOW). a check only, use fetch() to read it"""
    try:
        check_url(url)
        return True
    except FetchBlocked:
        return False


class FetchResponse:
    """the parts of requests.Response the tools use"""
    def __init__(self, url: str, status_code: int, headers, content: bytes):
        self.url, self.status_code, self.headers, self.content = url, status_code, headers, content
        self.reason = ""

    @property
    def text(self) -> str:
        charset = "utf-8"
        for part in self.headers.get("Content-Type", "").split(";"):
            if part.strip().lower().startswith("charset="):
                charset = part.split("=", 1)[1].strip().strip('"') or charset
        try:
            return self.content.decode(charset, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise urllib3.exceptions.HTTPError(f"{self.status_code} for {self.url}")


def _fetch_once(url: str, method: str, headers: dict, body, timeout: float, max_bytes: int) -> FetchResponse:
    parsed, port, ips = check_url(url)
    hostname = parsed.hostname
    host_header = hostname if not parsed.port else f"{hostname}:{parsed.port}"
    if ":" in hostname and not hostname.startswith("["):
        host_header = f"[{hostname}]" if not parsed.port else f"[{hostname}]:{parsed.port}"
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    send_headers = {k: v for k, v in (headers or {}).items() if k.lower() not in ("host", "connection", "content-length", "transfer-encoding")}
    send_headers["Host"] = host_header
    last_error = None
    for ip in ips:
        # connect to the checked address, never to a fresh dns answer
        if parsed.scheme == "https":
            pool = urllib3.HTTPSConnectionPool(str(ip), port, timeout=urllib3.Timeout(total=timeout), retries=False, maxsize=1,
                                               cert_reqs="CERT_REQUIRED", ca_certs=certifi.where(),
                                               server_hostname=hostname, assert_hostname=hostname)
        else:
            pool = urllib3.HTTPConnectionPool(str(ip), port, timeout=urllib3.Timeout(total=timeout), retries=False, maxsize=1)
        try:
            r = pool.urlopen(method, path, headers=send_headers, body=body, redirect=False, preload_content=False,
                             decode_content=True, assert_same_host=False)
            try:
                content = r.read(max_bytes + 1, decode_content=True) or b""
            finally:
                r.release_conn()
            if len(content) > max_bytes:
                content = content[:max_bytes]
                logger.debug(f"fetch {url}: cut at {max_bytes} bytes")
            return FetchResponse(url, r.status, r.headers, content)
        except (urllib3.exceptions.NewConnectionError, urllib3.exceptions.ConnectTimeoutError) as e:
            last_error = e      # next checked address of the same name
        finally:
            pool.close()
    raise last_error


def fetch(url: str, headers: Optional[dict] = None, timeout: float = 20, method: str = "GET", body=None,
          follow_redirects: bool = True, max_bytes: int = MAX_BYTES) -> FetchResponse:
    """GET (or method) url pinned to its checked address. redirects are followed by hand and every hop is
    checked again (a LAN host listed in HUB_FETCH_ALLOW can't redirect to one that isn't).
    raises FetchBlocked, or urllib3 errors for network problems"""
    for _ in range(MAX_REDIRECTS + 1):
        resp = _fetch_once(url, method, headers, body, timeout, max_bytes)
        location = resp.headers.get("Location")
        if not follow_redirects or resp.status_code not in REDIRECT_STATUS or not location:
            return resp
        url = urljoin(url, location)
        if resp.status_code == 303 or (resp.status_code in (301, 302) and method == "POST"):
            method, body = "GET", None
    logger.debug(f"fetch: more than {MAX_REDIRECTS} redirects, stopped at {url}")
    raise FetchBlocked(f"blocked: more than {MAX_REDIRECTS} redirects")
