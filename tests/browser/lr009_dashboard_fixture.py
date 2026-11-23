"""LR-009 dashboard fixture: the real LotRadar server and dashboard on loopback,
with a synthetic data directory and a fake historical dealer read.

Usage (from the repository root):
    python -B tests/browser/lr009_dashboard_fixture.py <empty-temp-data-dir> [--port 8799] [--engine headless|chrome] [--read-seconds 8]

Each fake dealer read takes --read-seconds and ignores Stop while "in flight"
(modelling a bounded dealer request that must drain), so the dashboard's
Stopping state is visible. Pause/Stop take effect at the next safe point.
No dealer website, browser engine or live LocalAppData profile is touched.
"""
import argparse
import json
import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('data_dir')
    parser.add_argument('--port', type=int, default=8799)
    parser.add_argument('--engine', choices=('headless', 'chrome'), default='headless')
    parser.add_argument('--read-seconds', type=float, default=8.0)
    args = parser.parse_args()
    data = Path(args.data_dir).resolve()
    live = (Path(os.environ.get('LOCALAPPDATA', '')) / 'MarketplaceScanner').resolve()
    if data == live or live in data.parents:
        raise SystemExit('Refusing to use the live MarketplaceScanner profile.')
    data.mkdir(parents=True, exist_ok=True)
    if any(data.iterdir()) and not (data / 'lr009_fixture.marker').exists():
        raise SystemExit('Use an empty, disposable data directory.')
    (data / 'lr009_fixture.marker').write_text('LR-009 synthetic fixture', 'utf-8')
    os.environ['LOTRADAR_DEALER_ENGINE'] = args.engine

    import server
    from headless_dealer import HeadlessDealer

    calls = []

    def fake_read(source, *, max_vehicles=250, progress=None, control=None, **_):
        calls.append(source)
        if progress:
            progress('loading_inventory', discovered=0, parsed=0, visited=0, failed=0)
        time.sleep(args.read_seconds)  # in-flight request: drains even after Stop
        if control:
            control.checkpoint()
        host = 'https://www.hamptontoyota.com' if source == 'toyota_used' else 'https://www.hamptonmitsubishi.com'
        make, model = ('Toyota', 'Camry') if source == 'toyota_used' else ('Mitsubishi', 'Outlander')
        rows = [{'url': f'{host}/used/2022-{make}-{model}-{n:020x}.htm', 'source': source, 'year': 2022,
                 'make': make, 'model': model, 'discovery_method': 'inventory_page', 'verified': False}
                for n in range(3)]
        if progress:
            progress('catalog_discovered', discovered=len(rows), parsed=len(rows), visited=0, failed=0)
        return {'source': source, 'scanned_at': server.utc(), 'records': rows, 'count': len(rows),
                'index_candidates': len(rows), 'warnings': [], 'verified': False, 'partial': True}

    store = server.MarketplaceStore(str(data))
    with patch.object(server, 'scan_basic_source', fake_read), \
         patch('vin_decode.VinDecoder', autospec=True), \
         patch.object(HeadlessDealer, 'ensure_ready', autospec=True):
        handler = server.create_handler(store, args.port, 'lr009-dashboard-' + os.urandom(6).hex())
        bridge = handler.headless_dealer.bridge
        bridge.headless_seen = time.monotonic() + 10 ** 6  # "connected" fake reader, no browser
        bridge.last_seen = time.monotonic() + 10 ** 6
        srv = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
        srv.daemon_threads = True
        print(json.dumps({'url': f'http://127.0.0.1:{args.port}/', 'engine': args.engine,
                          'data_dir': str(data), 'read_seconds': args.read_seconds}), flush=True)
        try:
            srv.serve_forever(poll_interval=0.1)
        finally:
            handler.photo_cache.close()
            srv.server_close()
            store.close()


if __name__ == '__main__':
    main()
