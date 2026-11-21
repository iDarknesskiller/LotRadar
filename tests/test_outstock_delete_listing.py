"""Out of Stock removal and Delete Listing reminders. Synthetic data in temp dirs only."""
import json,socket,sqlite3,sys,tempfile,threading,unittest,urllib.request,urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as S
from core import MarketplaceStore,SCHEMA

SRC='toyota_used'
VINS=['1HGCM82633A004352','2HGCM82633A004353','3HGCM82633A004354']
URLS=['https://www.facebook.com/marketplace/item/1111111111111/','https://www.facebook.com/marketplace/item/2222222222222/']

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.open_store()
        rows=[{'vin':v,'condition':'used','year':2022,'make':'Toyota','model':f'Model{i}','stock':f'T{i}','mileage':1000,'price':20000,
               'url':f'https://www.hamptontoyota.com/used/{i}.htm','images':[]} for i,v in enumerate(VINS)]
        self.store.import_feed(SRC,'json',json.dumps(rows))
    def open_store(self):
        self.store=MarketplaceStore(Path(self.tmp.name)/'data');self.addCleanup(self.store.close)
    def track(self,vin,url):
        self.store.create_draft(vin,SRC)
        self.store.db.execute("UPDATE drafts SET status='USER_CONFIRMED_PUBLISHED',published_url=? WHERE vin=?",(url,vin))
    def vins(self,st=None):return {v['vin'] for v in (st or self.store.state())['vehicles']}
    def row(self,vin):return self.store.db.execute('SELECT * FROM inventory_removals WHERE vin=?',(vin,)).fetchone()
    def pending(self):return self.store.state()['summary']['pending_fb_deletions']

class Removal(Base):
    def test_cleanup_issue_matrix_is_partitionable_by_tracking_status(self):
        self.track(VINS[0],URLS[0])
        self.store.record_link_check(SRC,'https://www.hamptontoyota.com/used/0.htm','unavailable')
        self.store.record_link_check(SRC,'https://www.hamptontoyota.com/used/1.htm','unavailable')
        st=self.store.state()
        by={r['vin']:r for r in st['vehicles']}
        self.assertTrue(by[VINS[0]]['listed'])
        self.assertFalse(by[VINS[1]]['listed'])
        issues=self.store.cleanup_status()
        self.assertIn(VINS[0],issues)
        self.assertIn(VINS[1],issues)
        states={v:('TRACKED_REVIEW' if r['listed'] else 'UNLISTED_REVIEW') for v,r in by.items()
                if v in issues}
        self.assertEqual(states,{VINS[0]:'TRACKED_REVIEW',VINS[1]:'UNLISTED_REVIEW'})
    def test_untracked_removal_hides_vehicle_without_reminder(self):
        st=self.store.remove_out_of_stock(VINS[0],True)
        self.assertNotIn(VINS[0],self.vins(st));self.assertEqual(self.row(VINS[0])['status'],'REMOVED');self.assertEqual(self.pending(),0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM sources WHERE vin=?',(VINS[0],)).fetchone()[0],1)
    def test_tracked_removal_creates_exactly_one_reminder_with_identity(self):
        self.track(VINS[0],URLS[0])
        self.store.remove_out_of_stock(VINS[0],True);self.store.remove_out_of_stock(VINS[0],True)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM inventory_removals').fetchone()[0],1)
        r=self.store.state()['removals'][0]
        self.assertEqual((r['status'],r['listing_url'],r['identity']['stock'],r['identity']['vin']),('PENDING_FB_DELETE',URLS[0],'T0',VINS[0]))
        self.assertEqual(r['open_url'],URLS[0]);self.assertEqual(self.pending(),1)
        self.assertEqual(self.store.db.execute('SELECT status FROM drafts WHERE vin=?',(VINS[0],)).fetchone()[0],'USER_CONFIRMED_PUBLISHED')
    def test_requires_explicit_confirmation_and_known_vin(self):
        for bad in (False,None,'true',1):
            with self.assertRaises(ValueError):self.store.remove_out_of_stock(VINS[0],bad)
        with self.assertRaises(ValueError):self.store.remove_out_of_stock('4HGCM82633A004355',True)
        with self.assertRaises(ValueError):self.store.remove_out_of_stock('bad',True)
        self.assertEqual(self.vins(),set(VINS))
    def test_link_check_failures_never_remove_a_vehicle(self):
        self.store.record_link_check(SRC,'https://www.hamptontoyota.com/used/0.htm','unavailable')
        self.store.record_link_check(SRC,'https://www.hamptontoyota.com/used/1.htm','check_failed')
        self.assertIn(VINS[0],self.store.cleanup_status());self.assertEqual(self.vins(),set(VINS));self.assertEqual(self.store.state()['removals'],[])
    def test_removed_vehicle_leaves_cleanup_status(self):
        self.store.record_link_check(SRC,'https://www.hamptontoyota.com/used/0.htm','unavailable')
        self.store.remove_out_of_stock(VINS[0],True);self.assertNotIn(VINS[0],self.store.cleanup_status())
    def test_restore_returns_vehicle_and_keeps_tracking(self):
        self.track(VINS[0],URLS[0]);self.store.remove_out_of_stock(VINS[0],True)
        with self.assertRaises(ValueError):self.store.restore_removed(VINS[0],False)
        st=self.store.restore_removed(VINS[0],True)
        self.assertIn(VINS[0],self.vins(st));self.assertEqual(self.pending(),0)
        self.assertTrue(next(v for v in st['vehicles'] if v['vin']==VINS[0])['listed'])
        self.store.remove_out_of_stock(VINS[0],True);self.assertEqual(self.pending(),1)  # re-removal recreates the reminder
    def test_rollback_on_failure_leaves_no_partial_state(self):
        self.track(VINS[0],URLS[0])
        self.store.db.execute('DROP TABLE audit');self.store.db.execute('CREATE TABLE audit(id INTEGER PRIMARY KEY, event TEXT NOT NULL CHECK(0))')
        with self.assertRaises(sqlite3.Error):self.store.remove_out_of_stock(VINS[0],True)
        self.assertIsNone(self.row(VINS[0]));self.assertFalse(self.store.db.in_transaction)

class BackupPolicy(Base):
    def fail_backup(self):
        def boom():raise OSError('synthetic backup failure')
        self.store.backup=boom
    def test_state_changes_take_a_backup_first(self):
        self.track(VINS[0],URLS[0]);calls=[]
        real=self.store.backup;self.store.backup=lambda:(calls.append(1),real())[1]
        self.store.remove_out_of_stock(VINS[0],True);self.assertEqual(len(calls),1)
        self.store.remove_out_of_stock(VINS[0],True);self.assertEqual(len(calls),1)   # duplicate click: no write, no backup
        self.store.restore_removed(VINS[0],True);self.assertEqual(len(calls),2)
        self.store.remove_out_of_stock(VINS[0],True);self.store.confirm_facebook_deleted(VINS[0],True,URLS[0]);self.assertEqual(len(calls),4)
        self.assertGreaterEqual(len(list(self.store.backup_dir.glob('backup-*.sqlite3'))),1)
    def test_backup_failure_aborts_removal_without_changes(self):
        self.track(VINS[0],URLS[0]);self.fail_backup()
        with self.assertRaises(OSError):self.store.remove_out_of_stock(VINS[0],True)
        self.assertIsNone(self.row(VINS[0]));self.assertIn(VINS[0],self.vins());self.assertFalse(self.store.db.in_transaction)
    def test_backup_failure_aborts_restore_without_changes(self):
        self.track(VINS[0],URLS[0]);self.store.remove_out_of_stock(VINS[0],True);self.fail_backup()
        with self.assertRaises(OSError):self.store.restore_removed(VINS[0],True)
        self.assertEqual(self.row(VINS[0])['status'],'PENDING_FB_DELETE');self.assertFalse(self.store.db.in_transaction)
    def test_backup_failure_aborts_completion_without_changes(self):
        self.track(VINS[0],URLS[0]);self.store.remove_out_of_stock(VINS[0],True);self.fail_backup()
        with self.assertRaises(OSError):self.store.confirm_facebook_deleted(VINS[0],True,URLS[0])
        self.assertEqual(self.row(VINS[0])['status'],'PENDING_FB_DELETE');self.assertEqual(self.store.listing_trash()['items'],[])
        self.assertIsNotNone(self.store.db.execute('SELECT 1 FROM drafts WHERE vin=?',(VINS[0],)).fetchone())
    def test_restore_rollback_on_sql_failure(self):
        self.track(VINS[0],URLS[0]);self.store.remove_out_of_stock(VINS[0],True)
        self.store.db.execute('DROP TABLE audit');self.store.db.execute('CREATE TABLE audit(id INTEGER PRIMARY KEY, event TEXT NOT NULL CHECK(0))')
        with self.assertRaises(sqlite3.Error):self.store.restore_removed(VINS[0],True)
        self.assertEqual(self.row(VINS[0])['status'],'PENDING_FB_DELETE');self.assertFalse(self.store.db.in_transaction)
    def test_integrity_check_after_operations(self):
        self.track(VINS[0],URLS[0]);self.store.remove_out_of_stock(VINS[0],True);self.store.confirm_facebook_deleted(VINS[0],True,URLS[0])
        self.assertEqual(self.store.verify_integrity(),'ok')

class Persistence(Base):
    def test_pending_survives_restart_rescan_and_partial_scan_and_site_failure(self):
        self.track(VINS[0],URLS[0]);self.store.remove_out_of_stock(VINS[0],True)
        rows=lambda vs:[{'vin':v,'condition':'used','year':2022,'make':'Toyota','model':'M','stock':'T9','mileage':1,'price':1,'url':'https://www.hamptontoyota.com/u/'+v,'images':[]} for v in vs]
        self.store.import_feed(SRC,'json',json.dumps(rows(VINS[1:])),complete=True)   # vehicle absent from a full scan
        self.store.import_feed(SRC,'json',json.dumps(rows(VINS[1:2])),complete=False) # partial scan
        self.store.record_link_check(SRC,'https://www.hamptontoyota.com/used/0.htm','check_failed')
        self.store.import_feed(SRC,'json',json.dumps(rows(VINS)),complete=True)       # vehicle reappears
        self.assertEqual(self.pending(),1);self.assertNotIn(VINS[0],self.vins())
        self.store.close();self.open_store()
        self.assertEqual(self.pending(),1);self.assertEqual(self.store.state()['removals'][0]['listing_url'],URLS[0])
    def test_schema_version_unchanged_so_rollback_to_prior_build_is_possible(self):self.assertEqual(SCHEMA,3)

class Completion(Base):
    def test_only_explicit_confirmation_clears_and_count_updates(self):
        self.track(VINS[0],URLS[0]);self.track(VINS[1],URLS[1])
        self.store.remove_out_of_stock(VINS[0],True);self.store.remove_out_of_stock(VINS[1],True);self.assertEqual(self.pending(),2)
        for bad in (False,None,'yes'):
            with self.assertRaises(ValueError):self.store.confirm_facebook_deleted(VINS[0],bad,URLS[0])
        with self.assertRaises(ValueError):self.store.confirm_facebook_deleted(VINS[0],True,URLS[1])  # another vehicle's listing
        with self.assertRaises(ValueError):self.store.confirm_facebook_deleted(VINS[0],True,None)
        self.assertEqual(self.pending(),2)
        st=self.store.confirm_facebook_deleted(VINS[0],True,URLS[0]);self.assertEqual(st['summary']['pending_fb_deletions'],1)
        self.assertEqual(self.row(VINS[0])['status'],'FB_DELETE_CONFIRMED')
        self.assertIsNone(self.store.db.execute('SELECT 1 FROM drafts WHERE vin=?',(VINS[0],)).fetchone())
        trash=self.store.listing_trash()['items'];self.assertEqual([t['vin'] for t in trash],[VINS[0]]);self.assertEqual(trash[0]['url'],URLS[0])
        self.assertEqual(self.store.confirm_facebook_deleted(VINS[0],True,URLS[0])['summary']['pending_fb_deletions'],1)  # duplicate click
        self.assertEqual(len(self.store.listing_trash()['items']),1)
        self.assertEqual(self.store.db.execute('SELECT status FROM drafts WHERE vin=?',(VINS[1],)).fetchone()[0],'USER_CONFIRMED_PUBLISHED')
    def test_untracked_vehicle_cannot_be_confirmed(self):
        self.store.remove_out_of_stock(VINS[0],True)
        with self.assertRaises(ValueError):self.store.confirm_facebook_deleted(VINS[0],True,'')
    def assert_pending_intact(self,vin,url,draft_status='USER_CONFIRMED_PUBLISHED'):
        self.assertEqual(self.row(vin)['status'],'PENDING_FB_DELETE');self.assertEqual(self.pending(),1)
        self.assertEqual(self.row(vin)['listing_url'],url);self.assertEqual(self.store.listing_trash()['items'],[])
    def test_changed_tracked_listing_blocks_completion(self):
        self.track(VINS[0],URLS[0]);self.store.remove_out_of_stock(VINS[0],True)
        self.store.db.execute("UPDATE drafts SET published_url=? WHERE vin=?",(URLS[1],VINS[0]))
        for expected in (URLS[0],URLS[1]):  # stale reminder URL and the new active URL are both refused
            with self.assertRaises(ValueError) as cm:self.store.confirm_facebook_deleted(VINS[0],True,expected)
            self.assertIn('facebook_listing_changed_since_review' if expected==URLS[1] else 'reconciliation_required',str(cm.exception))
        self.assert_pending_intact(VINS[0],URLS[0])
        d=self.store.db.execute('SELECT status,published_url FROM drafts WHERE vin=?',(VINS[0],)).fetchone()
        self.assertEqual((d['status'],d['published_url']),('USER_CONFIRMED_PUBLISHED',URLS[1]))
    def test_missing_or_archived_tracking_blocks_completion(self):
        self.track(VINS[0],URLS[0]);self.track(VINS[1],URLS[1])
        self.store.remove_out_of_stock(VINS[0],True);self.store.remove_out_of_stock(VINS[1],True)
        self.store.trash_listing(VINS[0],True)                                 # archived externally to local Trash
        self.store.db.execute('DELETE FROM drafts WHERE vin=?',(VINS[1],))      # record missing altogether
        for v,u in ((VINS[0],URLS[0]),(VINS[1],URLS[1])):
            with self.assertRaises(ValueError) as cm:self.store.confirm_facebook_deleted(v,True,u)
            self.assertIn('reconciliation_required',str(cm.exception));self.assertEqual(self.row(v)['status'],'PENDING_FB_DELETE')
        self.assertEqual(self.pending(),2);self.assertEqual(len(self.store.listing_trash()['items']),1)  # only the external archive
    def test_draft_no_longer_published_blocks_completion(self):
        self.track(VINS[0],URLS[0]);self.store.remove_out_of_stock(VINS[0],True)
        self.store.db.execute("UPDATE drafts SET status='USER_CONFIRMED_REMOVED' WHERE vin=?",(VINS[0],))
        with self.assertRaises(ValueError):self.store.confirm_facebook_deleted(VINS[0],True,URLS[0])
        self.assert_pending_intact(VINS[0],URLS[0])
    def test_rejected_completion_does_not_rotate_backups(self):
        self.track(VINS[0],URLS[0]);self.store.remove_out_of_stock(VINS[0],True)
        self.store.db.execute('DELETE FROM drafts WHERE vin=?',(VINS[0],))
        n=len(list(self.store.backup_dir.glob('backup-*.sqlite3')))
        with self.assertRaises(ValueError):self.store.confirm_facebook_deleted(VINS[0],True,URLS[0])
        self.assertEqual(len(list(self.store.backup_dir.glob('backup-*.sqlite3'))),n)
    def test_rollback_keeps_reminder_and_draft(self):
        self.track(VINS[0],URLS[0]);self.store.remove_out_of_stock(VINS[0],True)
        self.store.db.execute('DROP TABLE audit');self.store.db.execute('CREATE TABLE audit(id INTEGER PRIMARY KEY, event TEXT NOT NULL CHECK(0))')
        with self.assertRaises(sqlite3.Error):self.store.confirm_facebook_deleted(VINS[0],True,URLS[0])
        self.assertEqual(self.row(VINS[0])['status'],'PENDING_FB_DELETE');self.assertEqual(self.store.listing_trash()['items'],[])
        self.assertIsNotNone(self.store.db.execute('SELECT 1 FROM drafts WHERE vin=?',(VINS[0],)).fetchone())
    def test_pending_restore_is_explicit_only(self):
        self.track(VINS[0],URLS[0]);self.store.remove_out_of_stock(VINS[0],True)
        with self.assertRaises(ValueError):self.store.restore_removed(VINS[0],None)
        self.assertEqual(self.pending(),1)

class OpenUrl(Base):
    def test_open_url_is_canonical_and_per_vehicle_or_empty(self):
        self.track(VINS[0],URLS[0]+'?ref=x&evil=1');self.track(VINS[1],URLS[1])
        self.store.create_draft(VINS[2],SRC)
        self.store.db.execute("UPDATE drafts SET status='USER_CONFIRMED_PUBLISHED',published_url='javascript:alert(1)' WHERE vin=?",(VINS[2],))
        for v in VINS:self.store.remove_out_of_stock(v,True)
        by={r['vin']:r for r in self.store.state()['removals']}
        self.assertEqual(by[VINS[0]]['open_url'],URLS[0]);self.assertEqual(by[VINS[1]]['open_url'],URLS[1])
        self.assertEqual(by[VINS[2]]['open_url'],'');self.assertEqual(by[VINS[2]]['status'],'PENDING_FB_DELETE')  # invalid URL keeps reminder
        self.assertEqual(self.pending(),3)
        self.store.confirm_facebook_deleted(VINS[2],True,'javascript:alert(1)');self.assertEqual(self.pending(),2)
    def test_state_reads_do_not_change_tracking(self):
        self.track(VINS[0],URLS[0]);self.store.remove_out_of_stock(VINS[0],True)
        before=[tuple(r) for r in self.store.db.execute('SELECT * FROM inventory_removals')]+[tuple(r) for r in self.store.db.execute('SELECT * FROM drafts')]
        for _ in range(3):self.store.state()
        after=[tuple(r) for r in self.store.db.execute('SELECT * FROM inventory_removals')]+[tuple(r) for r in self.store.db.execute('SELECT * FROM drafts')]
        self.assertEqual(before,after)

class Api(Base):
    def setUp(self):
        super().setUp()
        sk=socket.socket();sk.bind(('127.0.0.1',0));self.port=sk.getsockname()[1];sk.close()
        H=S.create_handler(self.store,self.port,'tok');srv=ThreadingHTTPServer(('127.0.0.1',self.port),H);srv.daemon_threads=True
        threading.Thread(target=srv.serve_forever,daemon=True).start()
        self.addCleanup(lambda:(srv.shutdown(),srv.server_close(),H.photo_cache.close()))
    def post(self,body):
        req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/action',json.dumps(body).encode(),{'Content-Type':'application/json','X-SalesmanHub-Token':'tok'})
        try:
            with urllib.request.urlopen(req) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    def test_actions_over_http(self):
        self.track(VINS[0],URLS[0])
        self.assertEqual(self.post({'action':'remove_out_of_stock','vin':VINS[0]})[0],400)
        c,r=self.post({'action':'remove_out_of_stock','vin':VINS[0],'explicit_out_of_stock_confirmation':True})
        self.assertEqual((c,r['state']['summary']['pending_fb_deletions']),(200,1))
        self.assertEqual(self.post({'action':'confirm_facebook_deleted','vin':VINS[0],'explicit_manual_facebook_deletion':True,'expected_listing_url':URLS[1]})[0],400)
        c,r=self.post({'action':'confirm_facebook_deleted','vin':VINS[0],'explicit_manual_facebook_deletion':True,'expected_listing_url':URLS[0]})
        self.assertEqual((c,r['state']['summary']['pending_fb_deletions']),(200,0))

class Frontend(unittest.TestCase):
    root=Path(__file__).resolve().parents[1]
    def test_sidebar_sections(self):
        html=(self.root/'index.html').read_text(encoding='utf-8')
        self.assertNotIn('data-tab="published"',html);self.assertNotIn('Tracked on Facebook</button>',html)
        self.assertIn('data-tab="outstock"><span>⌁</span> Out of Stock</button>',html.replace('\n',''))
        self.assertIn('data-tab="deletelisting"',html);self.assertIn('id="delete-listing-badge"',html)
    def test_tracking_capabilities_remain_in_ui(self):
        js=(self.root/'app.js').read_text(encoding='utf-8')
        for needle in ('confirm_published','relink_facebook','track_existing','fb-compare','facebook-auto-check','btn-facebook-scan'):
            self.assertTrue(needle in js or needle in (self.root/'index.html').read_text(encoding='utf-8'),needle)
        self.assertNotIn("action:'trash_cleanup_listing'",js)
    def test_cleanup_queues_partition_by_published_tracking(self):
        js=(self.root/'app.js').read_text(encoding='utf-8')
        self.assertIn("tab==='outstock'&&( !cleanupIssues[r.vin] || r.listed || isPendingCleanupVin(r.vin))",js)
        self.assertIn("return r.listed?'TRACKED_REVIEW':'UNLISTED_REVIEW';",js)
        self.assertIn('const trackedCleanupCandidates=()=>',js)
        self.assertIn('Pending Facebook deletion',js)
        self.assertIn('Needs stock verification',js)
        self.assertIn('data-tracked-confirm=',js)
        self.assertIn('openTrackedListing(vin)',js)
        self.assertIn('badge.textContent=`${n?',js)
    def test_delete_listing_candidate_and_pending_actions_are_distinct(self):
        js=(self.root/'app.js').read_text(encoding='utf-8')
        self.assertIn('data-tracked-confirm',js)
        self.assertIn('data-delete-open',js)
        self.assertIn("I've deleted it on Facebook",js)
        self.assertIn('trackedCleanupCandidates().find(r=>r.vin===vin)',js)
        self.assertIn('pendingRemovals().find(r=>r.vin===vin)',js)
if __name__=='__main__':unittest.main()
