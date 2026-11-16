#!/usr/bin/env python3
"""Build and verify the LotRadar Windows installer package.

    python scripts/build_installer.py build  --mode production --asset-dir <private dir> [--out-dir dist]
    python scripts/build_installer.py build  --mode development [--asset-dir <dir>]
    python scripts/build_installer.py verify <package.zip> [--require-production]

Design rules (see docs/INSTALL.md):
  * Program files come ONLY from blobs committed at HEAD (never the working tree), so a
    package always matches a commit. Production builds also require a clean working tree.
  * Only an explicit allowlist is packaged. A tracked file that is neither allowlisted nor
    explicitly excluded fails the build, so new source files can never be silently omitted.
  * Private branding assets are NEVER read from the repository. They are supplied through
    --asset-dir (must be outside the repo or git-ignored) and validated before use.
  * Output is deterministic: sorted entries, fixed timestamps (commit time), STORED zip.
  * Install-Manifest.json is generated from the exact bytes being packaged.

Standard library only (Python 3.9+). Does not touch any installed program or user data.
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile

PRODUCT = 'LotRadar / Marketplace Scanner'
REPOSITORY = 'https://github.com/iDarknesskiller/LotRadar'
PAYLOAD_ROOT = 'MarketplaceScanner'
MANIFEST_NAME = 'Install-Manifest.json'
MANIFEST_SCHEMA = 2

# Program files installed to %LOCALAPPDATA%\Programs\MarketplaceScanner (repo path == payload path).
SOURCE_ALLOWLIST = [
    'Export Inventory for SalesmanHub.cmd',
    'Launch Marketplace Scanner.cmd',
    'Marketplace Bootstrap.ps1',
    'README - SCANNER.txt',
    'ai_copy.py',
    'app.js',
    'browser_trials.py',
    'chrome-extension/background.js',
    'chrome-extension/facebook_reader.js',
    'chrome-extension/manifest.json',
    'chrome-extension/marketplace_signal.js',
    'chrome-extension/popup.html',
    'chrome-extension/popup.js',
    'chrome_bridge.py',
    'connector_export.py',
    'core.py',
    'dealer_features.py',
    'dealer_site_scraper.py',
    'facebook_auto.py',
    'feed_sync.py',
    'headless_dealer.py',
    'index.html',
    'listing_transfer.py',
    'migrate_legacy.py',
    'photo-selection.css',
    'photo_cache.py',
    'photo_classify.py',
    'photo_selection.py',
    'refresh_policy.py',
    'requirements.txt',
    'server.py',
    'styles.css',
    'system_load.py',
    'trade_ready.py',
    'vin_decode.py',
]

# Tracked files that are intentionally NOT part of the installed program.
EXCLUDED_EXACT = {'.gitignore', '.gitattributes', 'README.md', 'AUDIT_README.txt', 'FILE_MANIFEST.json'}
EXCLUDED_PREFIXES = ('installer/', 'scripts/', 'docs/', 'tests/')

# Package-root files (outside the payload) taken from installer/.
PACKAGE_FILES = {
    'Installer.cmd': 'installer/Installer.cmd',
    'Install-LotRadar.ps1': 'installer/Install-LotRadar.ps1',
    'README - INSTALL.txt': 'installer/README - INSTALL.txt',
}

# Private assets: payload path -> (file name in --asset-dir, magic bytes, required in production)
ASSETS = {
    'branding/business_card.png': ('business_card.png', b'\x89PNG\r\n\x1a\n', True),
    'branding/dedication.jpg': ('dedication.jpg', b'\xff\xd8\xff', True),
    'LotRadar.ico': ('LotRadar.ico', b'\x00\x00\x01\x00', False),
}
MAX_ASSET_BYTES = 25 * 1024 * 1024

FORBIDDEN_PATH = re.compile(
    r'(^|/)(data|runtime|photos|photo_cache|browser[-_]profiles?|profiles|\.git|__pycache__|venv|\.venv|setup-venv)(/|$)'
    r'|\.(sqlite3?|sqlite3-(wal|shm|journal)|db|pem|key|pfx|log|exe|zip)$'
    r'|(^|/)\.env(\.|$)|token|secret|credential',
    re.IGNORECASE)
SECRET_PATTERNS = [
    ('OpenAI-style key', re.compile(rb'sk-[A-Za-z0-9_-]{20,}')),
    ('AWS access key', re.compile(rb'AKIA[0-9A-Z]{16}')),
    ('GitHub token', re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}')),
    ('Slack token', re.compile(rb'xox[abprs]-[A-Za-z0-9-]{10,}')),
    ('Private key block', re.compile(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    ('Google API key', re.compile(rb'AIza[0-9A-Za-z_-]{35}')),
]
BINARY_SUFFIXES = ('.png', '.jpg', '.jpeg', '.ico')


class BuildError(Exception):
    pass


def git(root, *args, text=False):
    try:
        out = subprocess.check_output(['git', '-C', root] + list(args), stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        raise BuildError('git %s failed: %s' % (' '.join(args), exc.stderr.decode('utf-8', 'replace').strip()))
    except FileNotFoundError:
        raise BuildError('git is not installed or not on PATH.')
    return out.decode('utf-8').strip() if text else out


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def scan_secrets(rel_path, data):
    """Return a list of problems for one packaged file (path rules + content patterns)."""
    problems = []
    is_asset = rel_path in ASSETS
    if not is_asset and FORBIDDEN_PATH.search(rel_path):
        problems.append('forbidden path: %s' % rel_path)
    if not rel_path.lower().endswith(BINARY_SUFFIXES):
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(data):
                problems.append('%s pattern in %s' % (label, rel_path))
    return problems


def safe_relative(path):
    parts = path.split('/')
    return bool(path) and ':' not in path and '\\' not in path and not path.startswith('/') \
        and all(p not in ('', '.', '..') for p in parts)


def load_committed_source(root):
    """Return (commit, commit_epoch, {repo_path: bytes}) read from HEAD blobs."""
    commit = git(root, 'rev-parse', 'HEAD', text=True)
    epoch = int(git(root, 'show', '-s', '--format=%ct', 'HEAD', text=True))
    tracked = [p for p in git(root, 'ls-tree', '-r', '-z', '--name-only', 'HEAD').decode('utf-8').split('\0') if p]
    allow = set(SOURCE_ALLOWLIST) | set(PACKAGE_FILES.values())
    missing = sorted(p for p in allow if p not in tracked)
    if missing:
        raise BuildError('Mandatory tracked files are missing at HEAD: ' + ', '.join(missing))
    unknown = sorted(p for p in tracked
                     if p not in allow and p not in EXCLUDED_EXACT and not p.startswith(EXCLUDED_PREFIXES))
    if unknown:
        raise BuildError('Tracked files are neither packaged nor explicitly excluded (update the allowlist '
                         'in scripts/build_installer.py): ' + ', '.join(unknown))
    blobs = {p: git(root, 'show', 'HEAD:' + p) for p in sorted(allow)}
    return commit, epoch, blobs


def load_assets(root, asset_dir, mode):
    """Validate and read private assets. Returns {payload_path: bytes}."""
    found = {}
    if not asset_dir:
        if mode == 'production':
            raise BuildError('Production builds require --asset-dir containing business_card.png and dedication.jpg.')
        return found
    asset_dir = os.path.realpath(asset_dir)
    if not os.path.isdir(asset_dir):
        raise BuildError('--asset-dir is not a directory: %s' % asset_dir)
    repo_real = os.path.realpath(root)
    inside_repo = os.path.commonpath([asset_dir, repo_real]) == repo_real
    for payload_path, (name, magic, required) in ASSETS.items():
        path = os.path.join(asset_dir, name)
        if not os.path.isfile(path):
            if required and mode == 'production':
                raise BuildError('Required private asset is missing: %s' % path)
            continue
        if inside_repo:
            rel = os.path.relpath(path, repo_real).replace(os.sep, '/')
            ignored = subprocess.run(['git', '-C', root, 'check-ignore', '-q', rel],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            if not ignored:
                raise BuildError('Asset %s is inside the repository and NOT git-ignored; refusing (risk of '
                                 'publishing private files). Keep assets outside the repo or under branding/.' % rel)
        size = os.path.getsize(path)
        if size < 16 or size > MAX_ASSET_BYTES:
            raise BuildError('Asset %s has an implausible size (%d bytes).' % (name, size))
        with open(path, 'rb') as handle:
            data = handle.read()
        if not data.startswith(magic):
            raise BuildError('Asset %s is not the expected file type (bad header).' % name)
        found[payload_path] = data
    if mode == 'production':
        for payload_path, (name, _magic, required) in ASSETS.items():
            if required and payload_path not in found:
                raise BuildError('Required private asset is missing: %s' % name)
    return found


def zip_bytes(entries, epoch):
    """entries: ordered list of (zip_name, bytes). Deterministic STORED archive."""
    stamp = time.gmtime(max(epoch, 315532800))  # ZIP cannot represent dates before 1980
    date_time = tuple(stamp[:6])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def build(root, mode, asset_dir, out_dir):
    root = os.path.realpath(root)
    commit, epoch, blobs = load_committed_source(root)
    dirty = git(root, 'status', '--porcelain', '--untracked-files=normal', text=True) != ''
    if dirty and mode == 'production':
        raise BuildError('Production builds require a clean working tree (commit or stash changes first).')
    assets = load_assets(root, asset_dir, mode)

    payload = {path: blobs[path] for path in SOURCE_ALLOWLIST}
    payload.update(assets)
    top = {name: blobs[src] for name, src in PACKAGE_FILES.items()}

    problems = []
    for path, data in sorted(payload.items()):
        problems += scan_secrets(path, data)
    for path, data in sorted(top.items()):
        problems += scan_secrets(path, data)
    if problems:
        raise BuildError('Package scan failed:\n  ' + '\n  '.join(problems))

    stamp = time.strftime('%Y%m%d', time.gmtime(epoch))
    version = '%s-%s' % (stamp, commit[:7])
    missing_branding = [p for p, (_n, _m, req) in ASSETS.items() if req and p not in payload]
    build_type = 'production' if mode == 'production' else 'development'
    manifest = {
        'product': PRODUCT,
        'manifest_schema': MANIFEST_SCHEMA,
        'package_version': version,
        'build_type': build_type,
        'source_repository': REPOSITORY,
        'source_commit': commit,
        'source_commit_time_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch)),
        'working_tree_clean': not dirty,
        'branding_assets_included': sorted(p for p in payload if p in ASSETS),
        'branding_assets_missing': sorted(missing_branding),
        'package_files': [{'path': n, 'sha256': sha256(d), 'bytes': len(d)} for n, d in sorted(top.items())],
        'payload_files': [{'path': p, 'sha256': sha256(d), 'bytes': len(d)} for p, d in sorted(payload.items())],
    }
    manifest_bytes = (json.dumps(manifest, indent=2) + '\n').encode('utf-8')

    entries = [(n, top[n]) for n in sorted(top)]
    entries.append((MANIFEST_NAME, manifest_bytes))
    entries += [(PAYLOAD_ROOT + '/' + p, payload[p]) for p in sorted(payload)]
    archive = zip_bytes(entries, epoch)

    suffix = '' if build_type == 'production' else ('-DEV' if not missing_branding else '-DEV-NOBRANDING')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'LotRadar-Installer-%s%s.zip' % (version, suffix))
    errors = verify_bytes(archive, require_production=(mode == 'production'))
    if errors:
        raise BuildError('Self-verification of the built package failed:\n  ' + '\n  '.join(errors))
    with open(out_path, 'wb') as handle:
        handle.write(archive)
    return out_path, manifest, sha256(archive), dirty


def verify_bytes(archive, require_production=False):
    """Independent re-check of a package. Returns a list of error strings (empty == OK)."""
    errors = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as exc:
        return ['not a valid ZIP: %s' % exc]
    with zf:
        names = [i.filename for i in zf.infolist() if not i.is_dir()]
        if len(names) != len(set(names)):
            errors.append('duplicate ZIP entries')
        for n in names:
            if not safe_relative(n):
                errors.append('unsafe ZIP entry name: %r' % n)
        if errors:
            return errors
        bad = zf.testzip()
        if bad:
            errors.append('CRC failure in %s' % bad)
        if MANIFEST_NAME not in names:
            return errors + ['%s is missing' % MANIFEST_NAME]
        try:
            manifest = json.loads(zf.read(MANIFEST_NAME).decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as exc:
            return errors + ['manifest is not valid JSON: %s' % exc]
        if manifest.get('product') != PRODUCT:
            errors.append('manifest product mismatch')
        if require_production and manifest.get('build_type') != 'production':
            errors.append('not a production package (build_type=%r)' % manifest.get('build_type'))
        for key in ('package_version', 'source_commit'):
            if not manifest.get(key):
                errors.append('manifest field missing: ' + key)

        expected = {}
        for section, prefix in (('package_files', ''), ('payload_files', PAYLOAD_ROOT + '/')):
            for item in manifest.get(section) or []:
                path = prefix + str(item.get('path'))
                if not safe_relative(str(item.get('path'))):
                    errors.append('unsafe manifest path: %r' % item.get('path'))
                if path in expected:
                    errors.append('manifest lists %s more than once' % path)
                if not re.fullmatch(r'[0-9a-f]{64}', str(item.get('sha256'))):
                    errors.append('bad sha256 for %s' % path)
                expected[path] = item
        if not manifest.get('payload_files'):
            errors.append('manifest lists no payload files')
        listed = set(expected)
        actual = set(names) - {MANIFEST_NAME}
        for path in sorted(listed - actual):
            errors.append('listed but missing from package: %s' % path)
        for path in sorted(actual - listed):
            errors.append('in package but not in manifest: %s' % path)
            rel = path[len(PAYLOAD_ROOT) + 1:] if path.startswith(PAYLOAD_ROOT + '/') else path
            errors += scan_secrets(rel, zf.read(path))
        for path in sorted(listed & actual):
            data = zf.read(path)
            item = expected[path]
            if sha256(data) != item.get('sha256'):
                errors.append('SHA-256 mismatch: %s' % path)
            if len(data) != item.get('bytes'):
                errors.append('size mismatch: %s' % path)
            rel = path[len(PAYLOAD_ROOT) + 1:] if path.startswith(PAYLOAD_ROOT + '/') else path
            errors += scan_secrets(rel, data)
        for path in SOURCE_ALLOWLIST:
            if PAYLOAD_ROOT + '/' + path not in actual:
                errors.append('mandatory program file missing: %s' % path)
        for name in PACKAGE_FILES:
            if name not in actual:
                errors.append('mandatory package file missing: %s' % name)
        if manifest.get('build_type') == 'production':
            for payload_path, (_n, _m, required) in ASSETS.items():
                if required and PAYLOAD_ROOT + '/' + payload_path not in actual:
                    errors.append('production package lacks required asset: %s' % payload_path)
    return errors


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build', help='build an installer ZIP from committed source')
    b.add_argument('--mode', choices=('production', 'development'), required=True)
    b.add_argument('--asset-dir', help='private folder with business_card.png, dedication.jpg [, LotRadar.ico]')
    b.add_argument('--out-dir', default=None, help='output folder (default: <repo>/dist)')
    b.add_argument('--repo-root', default=os.path.dirname(here))
    v = sub.add_parser('verify', help='verify an existing installer ZIP')
    v.add_argument('package')
    v.add_argument('--require-production', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'build':
            out_dir = args.out_dir or os.path.join(args.repo_root, 'dist')
            path, manifest, digest, dirty = build(args.repo_root, args.mode, args.asset_dir, out_dir)
            print('Built %s' % path)
            print('  package_version : %s (%s)' % (manifest['package_version'], manifest['build_type']))
            print('  source_commit   : %s' % manifest['source_commit'])
            print('  payload files   : %d' % len(manifest['payload_files']))
            print('  branding missing: %s' % (', '.join(manifest['branding_assets_missing']) or 'none'))
            print('  zip sha256      : %s' % digest)
            if dirty:
                print('WARNING: working tree has uncommitted changes; they are NOT in the package.')
            if manifest['build_type'] != 'production':
                print('WARNING: development package; do not distribute as a release.')
        else:
            with open(args.package, 'rb') as handle:
                errors = verify_bytes(handle.read(), args.require_production)
            if errors:
                print('VERIFY FAILED:')
                for e in errors:
                    print('  - ' + e)
                return 1
            print('VERIFY OK: %s' % args.package)
    except BuildError as exc:
        print('ERROR: %s' % exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print('ERROR: %s' % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
