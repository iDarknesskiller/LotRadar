#!/usr/bin/env python3
"""Safely copy, never move, existing Marketplace data to separate scanner folder.

Deliberately requires explicit --apply and an absent destination data folder.
Legacy runtime, secrets, SQLite WAL files, logs and caches that carry tokens
are excluded. Copies SQLite with online backup API for consistency.
"""
from __future__ import annotations
import argparse, os, sqlite3, shutil, socket, sys, uuid
from pathlib import Path

SKIP_ROOT={'venv','runtime','__pycache__','chrome_bridge_key.txt','marketplace_launcher_exit.log',
           'marketplace_startup_error.log'}
SKIP_SUFFIX={'.pyc','.wal','.shm'}

def paths():
    base=Path(os.getenv('LOCALAPPDATA') or (Path.home()/'AppData'/'Local'))
    return base/'SalesmanHub'/'MarketplaceManager', base/'MarketplaceScanner'/'data'

def occupied():
    with socket.socket() as s:
        s.settimeout(.4)
        return s.connect_ex(('127.0.0.1',8765))==0

def safe_file(item, root):
    rel=item.relative_to(root)
    if (rel.parts[0] in SKIP_ROOT or item.name in SKIP_ROOT or item.suffix.lower() in SKIP_SUFFIX
        or item.name.endswith(('-wal', '-shm', '-journal'))):
        return False
    return not any(part in ('venv','runtime','__pycache__') for part in rel.parts)

def apply_copy(src,dest):
    if not src.is_dir():raise ValueError('Original Marketplace data folder does not exist')
    if dest.exists():raise ValueError('New scanner data directory already exists; refusing to overwrite')
    if occupied():raise ValueError('Port 8765 is busy. Close the original scanner before migrating.')
    parent=dest.parent;parent.mkdir(parents=True,exist_ok=True)
    stage=parent/('.data-migration-'+uuid.uuid4().hex)
    copied=0
    stage.mkdir()
    try:
        for item in src.rglob('*'):
            if not safe_file(item,src):continue
            if item.is_symlink():raise ValueError('Unexpected symbolic link in original data; stopped safely')
            target=stage/item.relative_to(src)
            if item.is_dir():
                target.mkdir(parents=True,exist_ok=True)
                continue
            if not item.is_file():continue
            target.parent.mkdir(parents=True,exist_ok=True)
            if item.name=='marketplace.sqlite3' and item.parent==src:
                s=sqlite3.connect(item.resolve().as_uri()+'?mode=ro',uri=True)
                d=sqlite3.connect(target)
                try:
                    s.backup(d)
                    r=d.execute('PRAGMA integrity_check').fetchone()
                    if r is None or r[0]!='ok':raise RuntimeError('SQLite integrity check failed')
                finally:
                    d.close();s.close()
            else:
                shutil.copy2(item,target)
            copied+=1
        if dest.exists():raise ValueError('Data folder appeared during migration. Refusing to overwrite')
        stage.rename(dest)
        print('COPIED',copied,'files to',dest)
        print('Old data is untouched in:',src)
        print('Browser pairing key was intentionally not copied. Re-pair Chrome reader.')
    except Exception:
        shutil.rmtree(stage,ignore_errors=True)
        raise

def main():
    p=argparse.ArgumentParser(description='Copy old Marketplace user data to independent scanner (no deletion)')
    p.add_argument('--apply',action='store_true',help='Explicitly perform the COPY')
    p.add_argument('--source',type=Path,help='Override source for testing')
    p.add_argument('--destination',type=Path,help='Override destination for testing')
    args=p.parse_args()
    src,dst=paths()
    src=args.source or src;dst=args.destination or dst
    print('Original:',src,'\nNew:',dst)
    if not args.apply:
        print('PREVIEW ONLY. Nothing has changed. Use --apply to copy data.')
        return 0
    try:apply_copy(src,dst)
    except Exception as ex:
        print('Migration stopped:',type(ex).__name__,str(ex),file=sys.stderr)
        print('Original data was never modified.',file=sys.stderr)
        return 2
    return 0
if __name__=='__main__':sys.exit(main())
