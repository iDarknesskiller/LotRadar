#!/usr/bin/env python3
"""Read-only, allowlisted offline inventory export for future SalesmanHub connector.

This does NOT post data to a server. Treat exported JSON as UNTRUSTED until it
passes user authorization, schema validation and freshness checks at the Hub.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sqlite3, sys, uuid
from pathlib import Path
from datetime import datetime, timezone

SOURCES={'toyota_used','mitsubishi_used'}
ATTRS=('vin','year','make','model','trim','condition','stock','mileage','price_cents',
       'availability','url','sync_state','fresh','images_approved','demo_only')
MAX_ROWS=50000

def canon(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()
def now():return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')

def scanner_home():
    return Path(os.getenv('LOCALAPPDATA') or (Path.home()/'AppData'/'Local'))/'MarketplaceScanner'

def export(db_path,out_dir):
    if not db_path.is_file():raise FileNotFoundError('Database not found. Start scanner or migrate old data first')
    conn=sqlite3.connect(db_path.resolve().as_uri()+'?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    try:
        rows=conn.execute('SELECT vin,source,record_json,seen_at,missing_count FROM sources ORDER BY source,vin LIMIT ?', (MAX_ROWS+1,)).fetchall()
    finally:conn.close()
    if len(rows)>MAX_ROWS:raise ValueError('Inventory exceeds export safety limit')
    records=[]
    for r in rows:
        if r['source'] not in SOURCES:continue
        if not isinstance(r['vin'],str) or len(r['vin'])!=17:continue
        data=json.loads(r['record_json'])
        if not isinstance(data,dict):continue
        body={k:data.get(k) for k in ATTRS if k in data}
        body['vin']=r['vin']
        body['source']=r['source']
        body['observed_at_utc']=r['seen_at']
        body['missing_count']=r['missing_count']
        # Do not infer dealer availability from a partial scan.
        body['dealer_availability_not_final']=True
        if not isinstance(body.get('url'),str):body.pop('url',None)
        if not isinstance(body.get('price_cents'),int):body.pop('price_cents',None)
        record_hash=sha(canon(body))
        records.append({'entity':'marketplace.dealer_vehicle','record_id':f"{r['source']}:{r['vin']}",
                        'operation_id':sha('scanner-v1|'+r['source']+'|'+r['vin']+'|'+record_hash),
                        'content_hash':record_hash,'payload':body})
    batch_hash=sha(canon([r['operation_id'] for r in records]))
    out_dir.mkdir(parents=True,exist_ok=True)
    state=out_dir/'last-export.sha256'
    if state.exists() and state.read_text(encoding='ascii').strip()==batch_hash:
        print('No inventory changes since previous export. Nothing new queued.')
        return None
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path=out_dir/('inventory-'+stamp+'-'+uuid.uuid4().hex[:8]+'.json')
    envelope={'schema':'salesmanhub-marketplace-exchange/v1','producer':'marketplace-scanner',
              'generated_at_utc':now(),'batch_id':str(uuid.uuid4()),
              'sync_status':'pending_hub_import','records':records,
              'notes':'Snapshot only. Not validated by SalesmanHub. Does not confirm availability or publication.'}
    temp=out_dir/(path.name+'.tmp')
    temp.write_text(json.dumps(envelope,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,path)
    # State marker is updated only after durable atomic outbox file creation.
    marker=out_dir/('.last-export-'+uuid.uuid4().hex+'.tmp')
    marker.write_text(batch_hash+'\n',encoding='ascii')
    os.replace(marker,state)
    print('Created',len(records),'record(s) in:',path)
    print('This file is not yet sent to or accepted by SalesmanHub.')
    return path

def main():
    p=argparse.ArgumentParser(description='Export dealer inventory into scanner-to-Hub pending outbox')
    p.add_argument('--data-dir',type=Path,default=scanner_home()/'data')
    p.add_argument('--out-dir',type=Path)
    args=p.parse_args()
    dest=args.out_dir or scanner_home()/'exchange'/'outbox'
    try:export(args.data_dir/'marketplace.sqlite3',dest)
    except Exception as ex:
        print('Export failed:',type(ex).__name__,str(ex),file=sys.stderr)
        return 2
    return 0
if __name__=='__main__':sys.exit(main())
