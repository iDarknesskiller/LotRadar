"""Local, read-only pilots. Never imports records, publishes, or copies browser cookies."""
import argparse,asyncio,json,os,sqlite3,time
from pathlib import Path
from urllib.parse import urlsplit
from system_load import SystemLoad
BASE=Path(__file__).resolve().parent
ROOT=Path(os.getenv('LOCALAPPDATA',str(Path.home())))/'MarketplaceScanner'

def saved_rows():
    db=ROOT/'data'/'marketplace.sqlite3'
    if not db.is_file():raise ValueError('LotRadar inventory database not found')
    return sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)

def facebook_urls():
    with saved_rows() as db:
        rows=db.execute("SELECT published_url FROM drafts WHERE status='USER_CONFIRMED_PUBLISHED' ORDER BY vin").fetchall()
    urls=[]
    for (url,) in rows:
        p=urlsplit(url or '')
        import re
        if p.scheme=='https' and p.hostname in ('www.facebook.com','facebook.com','m.facebook.com') and re.fullmatch(r'/marketplace/item/\d{8,24}/?',p.path):
            canonical='https://www.facebook.com'+p.path.rstrip('/')
            if canonical not in urls:urls.append(canonical)
        if len(urls)==5:break
    return urls

async def facebook(login=False):
    from playwright.async_api import async_playwright
    profile=ROOT/'facebook-trial-profile'
    urls=[] if login else facebook_urls()
    if not login and not urls:raise ValueError('No published Facebook listing links saved in LotRadar')
    report={'trial':'facebook_headless_five','results':[],'writes_to_inventory':False}
    async with async_playwright() as p:
        context=await p.chromium.launch_persistent_context(str(profile),channel='chrome',headless=not login,accept_downloads=False)
        try:
            page=await context.new_page()
            if login:
                await page.goto('https://www.facebook.com/',wait_until='domcontentloaded')
                print('Sign in yourself in the opened Chrome window. Complete any checkpoint there.')
                await asyncio.to_thread(input,'When finished, press Enter here to close and save this separate profile: ')
                return {'trial':'profile_setup','result':'User finished profile setup; authentication not independently verified'}
            script=(BASE/'chrome-extension'/'facebook_reader.js').read_text('utf-8')
            for url in urls:
                started=time.monotonic();item={'url':url}
                try:
                    response=await page.goto(url,wait_until='domcontentloaded',timeout=30000)
                    await page.wait_for_timeout(2500)
                    path=urlsplit(page.url).path
                    if '/login' in path or '/checkpoint' in path or await page.locator('input[type=password]').count():
                        item['result']='login_or_checkpoint_required';report['results'].append(item);break
                    if response and response.status in (401,403,429):
                        item['result']='access_blocked';report['results'].append(item);break
                    if response and response.status>=500:raise ValueError('server_unavailable')
                    snapshot=await page.evaluate(script)
                    if snapshot.get('error') or not snapshot.get('title'):
                        item['result']='inconclusive'
                    elif urlsplit(snapshot.get('url','')).path.rstrip('/')!=urlsplit(url).path.rstrip('/'):
                        item['result']='listing_identity_mismatch'
                    else:
                        item.update(result='readable',title=snapshot['title'],price=snapshot.get('price'),
                                    mileage=snapshot.get('mileage'),status=snapshot.get('status'),fields_found=snapshot.get('fields_found'))
                except Exception as exc:item.update(result='failed',error=type(exc).__name__)
                item['seconds']=round(time.monotonic()-started,2);report['results'].append(item)
                print(item['result'],url)
                await page.wait_for_timeout(1500)
        finally:await context.close()
    report['note']='Compare these same five links in visible Chrome. Inconclusive is not sold. Login/checkpoint requires running Facebook Trial Login.cmd.'
    return report

async def benchmark():
    from headless_dealer import HeadlessDealer,reader_script,allowed_job
    from dealer_site_scraper import parse_vehicle_page
    from playwright.async_api import async_playwright
    with saved_rows() as db:rows=db.execute("SELECT source,record_json FROM sources WHERE source IN ('toyota_used','mitsubishi_used') ORDER BY vin,source LIMIT 40").fetchall()
    jobs=[]
    for src,raw in rows:
        rec=json.loads(raw);job={'source':src,'url':rec.get('url',''),'kind':'vehicle'}
        if allowed_job(job):jobs.append(job)
        if len(jobs)==20:break
    if not jobs:raise ValueError('No saved dealer links available for benchmark')
    report={'trial':'same_urls_10_vs_16','url_count':len(jobs),'runs':[],'writes_to_inventory':False}
    worker=HeadlessDealer.__new__(HeadlessDealer);worker.script=reader_script();worker.user_agent=None
    monitor=SystemLoad()
    async with async_playwright() as p:
        for cap in (10,16):
            browser=await worker._launch(p.chromium);sem=asyncio.Semaphore(cap);results=[];samples=[];denials=0;abort=False
            async def sample():
                nonlocal abort
                while True:
                    reading=monitor.sample();samples.append(reading)
                    if reading.get('available') and (reading['available_gb']<1 or reading['memory_percent']>=95):abort=True
                    await asyncio.sleep(2)
            async def run(job):
                nonlocal denials
                async with sem:
                    if denials>=3 or abort:return results.append({'url':job['url'],'outcome':'skipped_pressure_or_denials'})
                    start=time.monotonic()
                    try:
                        result=await asyncio.wait_for(worker._read(browser,job),105)
                        outcome=result.get('outcome')
                        if outcome=='access_denied':denials+=1
                        record={'url':job['url'],'outcome':outcome}
                        if outcome=='ok':
                            car=parse_vehicle_page(result['html'],job['url'],job['source'],rendered_text=result.get('text',''))
                            record.update(vin=car.get('vin'),photos=len(car.get('images') or []),mileage=car.get('mileage'),price=car.get('price'),gallery_expected=result.get('gallery_expected'))
                    except Exception as exc:record={'url':job['url'],'outcome':type(exc).__name__}
                    record['seconds']=round(time.monotonic()-start,2);results.append(record)
            start=time.monotonic();sampler=asyncio.create_task(sample())
            try:await asyncio.gather(*(run(job) for job in jobs))
            finally:
                sampler.cancel();await asyncio.gather(sampler,return_exceptions=True);await browser.close()
            elapsed=time.monotonic()-start;success=sum(r.get('outcome')=='ok' for r in results)
            report['runs'].append({'cap':cap,'seconds':round(elapsed,2),'successful_per_minute':round(success*60/elapsed,2),'results':results,'system_load':samples})
            print('Cap',cap,':',success,'readable pages;',round(elapsed,1),'seconds')
            if denials>=3 or abort:break
            await asyncio.sleep(3)
    report['note']='Order is 10 then 16; website/cache variation may affect results. Compare successful throughput and field/photo coverage, not elapsed time alone.'
    return report

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['facebook-login','facebook-test','dealer-benchmark']);args=parser.parse_args()
    result=await (benchmark() if args.mode=='dealer-benchmark' else facebook(args.mode=='facebook-login'))
    dest=ROOT/'TrialReports';dest.mkdir(parents=True,exist_ok=True)
    path=dest/(args.mode+'-'+time.strftime('%Y%m%d-%H%M%S')+'.json');path.write_text(json.dumps(result,indent=2),'utf-8');print('Report:',path)
if __name__=='__main__':
    try:asyncio.run(main())
    except Exception as exc:print('Trial stopped:',type(exc).__name__,str(exc)[:180]);raise SystemExit(1)
