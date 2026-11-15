"""Opt-in authorized feed connector. No dealership-site scraping by default.

Configuration is private user data under ~/.../MarketplaceManager/authorized_feeds.json.
Each remote feed requires dealership approval; URL must be HTTPS and public.
"""
from __future__ import annotations
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import time
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler
from core import SOURCES, MAX_FEED_CHARS


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('authorized_feed_redirects_are_disabled')


def validate_public_feed_url(url):
    try:
        p = urlparse(url)
        if p.scheme != 'https' or p.port not in (None, 443) or not p.hostname or p.username or p.password:
            raise ValueError('https_public_feed_required')
        host = p.hostname
        if host.lower() in {'localhost', 'localhost.localdomain'}:
            raise ValueError('local_feed_endpoint_forbidden')
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses:
            raise ValueError('feed_hostname_unresolved')
        for info in addresses:
            addr = ipaddress.ip_address(info[4][0])
            if not addr.is_global:
                raise ValueError('private_or_reserved_feed_network_forbidden')
        return url
    except (OSError, ValueError, TypeError) as ex:
        raise ValueError('unsafe_or_unreachable_feed_url: ' + str(ex)) from ex


def fetch_authorized_https(url, headers=None, retries=3):
    validate_public_feed_url(url)
    opener = build_opener(RejectRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    headers = headers or {}
    last = None
    for i in range(retries):
        try:
            req = Request(url, headers={'User-Agent': 'SalesmanHub-Marketplace-Cycle4/0.4 (authorized dealer feed)',
                                        'Accept': 'application/json,text/csv,text/plain', **headers})
            with opener.open(req, timeout=15) as resp:
                if resp.status != 200:
                    raise ValueError('feed_http_status_' + str(resp.status))
                raw = resp.read(MAX_FEED_CHARS + 1)
                if len(raw) > MAX_FEED_CHARS:
                    raise ValueError('feed_too_large')
                return raw.decode('utf-8-sig')
        except (OSError, ValueError, UnicodeError) as ex:
            last = ex
            if i < retries - 1:
                time.sleep(min(2 ** i, 4))
    raise ValueError('authorized_feed_fetch_failed: ' + str(last))


def load_authorized_config(data_dir):
    path = Path(data_dir) / 'authorized_feeds.json'
    if not path.exists():
        return {}
    obj = json.loads(path.read_text(encoding='utf8'))
    if not isinstance(obj, dict) or set(obj) - set(SOURCES):
        raise ValueError('authorized_feeds_config_invalid')
    return obj


def sync_configured(store, only_source=None):
    settings = load_authorized_config(store.root)
    results = {}
    if only_source and only_source not in SOURCES:
        raise ValueError('unsupported_source')
    for source in SOURCES:
        if only_source and source != only_source:
            continue
        cfg = settings.get(source)
        if not cfg:
            continue
        try:
            if not isinstance(cfg, dict) or cfg.get('approved_by_dealership') is not True:
                raise ValueError('requires_dealership_authorization')
            fmt = cfg.get('format')
            if fmt not in ('csv', 'json'):
                raise ValueError('format_must_be_csv_or_json')
            if cfg.get('type') == 'local_file':
                # Only an explicitly staged file within the private feeds/ directory.
                filename = cfg.get('filename')
                if not isinstance(filename, str) or Path(filename).name != filename or filename in ('.','..'):
                    raise ValueError('invalid_feed_filename')
                folder = store.root / 'feeds'
                path = folder / filename
                if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FEED_CHARS:
                    raise ValueError('authorized_local_feed_unavailable')
                text = path.read_text(encoding='utf-8-sig')
            elif cfg.get('type') == 'https':
                url = cfg.get('url')
                headers = {}
                if cfg.get('bearer_token_env'):
                    key = str(cfg['bearer_token_env'])
                    if not key.startswith('SALESMANHUB_FEED_') or len(key) > 100:
                        raise ValueError('invalid_token_env_reference')
                    secret = os.environ.get(key)
                    if not secret:
                        raise ValueError('missing_configured_feed_token')
                    headers['Authorization'] = 'Bearer ' + secret
                text = fetch_authorized_https(url, headers=headers)
            else:
                raise ValueError('unsupported_feed_type')
            # Never assume a configured feed is a full inventory snapshot.
            # The dealer/export owner must explicitly mark this feed as a verified
            # full snapshot. Otherwise it can add/update, but not mark VINs missing.
            complete = cfg.get('full_snapshot_confirmed') is True
            results[source] = {'ok': True, 'result': store.import_feed(source, fmt, text, complete=complete)}
        except Exception as ex:
            # A feed failure never means vehicles are sold and never writes a missing snapshot.
            results[source] = {'ok': False, 'error': str(ex)}
    return results
