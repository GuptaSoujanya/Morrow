"""Small, bounded public-page reader for checking research evidence (no cookies)."""
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


def public_url(value):
    try:
        url = urlsplit(str(value))
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            return False
        if url.port not in (None, 80, 443) or any(c in str(value) for c in ('\r', '\n', '\x00')):
            return False
        host = url.hostname.lower().rstrip('.')
        if host == 'localhost' or host.endswith(('.local', '.localhost', '.internal')) or '.' not in host:
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


def fetch_page(url):
    for _ in range(4):
        if not public_url(url):
            raise ValueError('Only public HTTP(S) source pages can be checked.')
        part = urlsplit(url)
        port = part.port or (443 if part.scheme == 'https' else 80)
        addresses = {record[4][0] for record in socket.getaddrinfo(part.hostname, port, type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError('The source resolves to a private address.')
        # Pin the checked address to prevent a second DNS lookup or proxy from reaching a local service.
        connection = http.client.HTTPConnection(part.hostname, port, timeout=8)
        connection.sock = socket.create_connection((sorted(addresses)[0], port), timeout=8)
        if part.scheme == 'https':
            connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=part.hostname)
        try:
            connection.request('GET', (part.path or '/') + ('?' + part.query if part.query else ''),
                               headers={'User-Agent': 'MorrowCompanyResearch/1.0', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = urljoin(url, response.getheader('Location', ''))
                continue
            if response.status != 200:
                raise ValueError('Source returned HTTP %s.' % response.status)
            content_type = response.getheader('Content-Type', '').lower()
            if not any(t in content_type for t in ('text/', 'application/json', 'application/ld+json', 'xhtml')):
                raise ValueError('Source is not a readable web page.')
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError('Source exceeds the page size limit.')
            soup = BeautifulSoup(raw, 'html.parser')
            links = [urljoin(url, a['href']) for a in soup.select('a[href]')]
            for element in soup(['script', 'style', 'noscript']):
                element.decompose()
            return {'url': url, 'text': soup.get_text(' ', strip=True), 'links': links}
        finally:
            connection.close()
    raise ValueError('Source redirected too many times.')
