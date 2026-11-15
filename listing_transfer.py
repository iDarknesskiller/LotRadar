"""Manual Facebook listing transfer package. No Meta login, APIs, or posting."""
from __future__ import annotations
import csv
import io
import json
import re
from zipfile import ZipFile, ZIP_DEFLATED
from core import record_is_fresh, source_fingerprint


def build_transfer_kit(store, vin, cached_photos=None, allowed_photo_urls=None):
    """Only export a user-approved and still-current draft; returns ZIP bytes."""
    vin=str(vin or '').strip().upper()
    with store.lock:
        state=store.state()
        item=next((x for x in state['vehicles'] if x['vin']==vin),None)
        if not item or not item.get('draft'):
            raise ValueError('draft_not_found')
        draft=item['draft']
        if draft['status']!='READY_FOR_MANUAL_PUBLISH':
            raise ValueError('approve_current_draft_before_transfer')
        rec=item['sources'].get(draft['source'])
        if (not rec or rec['sync_state']!='present' or not rec['fresh'] or rec['availability'] in ('sold','unavailable')
            or not rec['images_approved'] or not rec['images'] or rec['demo_only']
            or source_fingerprint(rec)!=draft['snapshot_hash'] or rec['price_cents']!=draft['price_cents']):
            raise ValueError('listing_changed_or_photo_permission_missing; reapprove_first')
        if ('price_conflict' in item['holds'] and not draft['conflict_ack']):
            raise ValueError('price_conflict_needs_confirmation')
        price=str(draft['price_cents']//100) if draft['price_cents']%100==0 else f"{draft['price_cents']/100:.2f}"
        result={'vin':vin,'title':draft['title'],'price':price,'description':draft['description'],
                'source':draft['source'],'dealer_vehicle_url':rec['url'],'stock':rec['stock'],
                'year':rec['year'],'make':rec['make'],'model':rec['model'],'trim':rec['trim'],
                'condition':rec['condition'],'mileage':rec['mileage'],
                'photo_urls':list(allowed_photo_urls or []),'user_review_required':True,'published':False}
        photos = cached_photos or []
        if len(photos)>251 or sum(len(body) for _,body in photos)>180*1024*1024:
            raise ValueError('cached_photo_export_exceeds_limit')
        buf=io.BytesIO()
        with ZipFile(buf,'w',compression=ZIP_DEFLATED) as z:
            z.writestr('README_FIRST.txt',
                'LOTRADAR -> FACEBOOK MARKETPLACE MANUAL LISTING KIT\n\n'
                '1. Confirm availability and selling price with the dealership.\n'
                '2. Open Facebook Marketplace and choose the VEHICLE listing category, if available.\n'
                '3. Copy title, price, description and mileage from this kit.\n'
                '4. Upload photos from the photos folder if present. Only use photos you are authorized to reuse.\n'
                '5. If fewer files are present than photo URLs, the missing downloads failed; review photo_urls.txt.\n'
                '6. Review every Facebook field and personally click Publish.\n'
                '7. Copy the published Marketplace URL back into LotRadar.\n\n'
                'Photo 1 is the dealership cover image with your business card over the phone plate where recognized.\n'
                'Photo 2 is your dedication artwork. All originals remain unmodified.\n'
                'This ZIP includes locally cached photos where available, plus links for missing files.\n'
                'No Facebook form was filled or posted. No photo rights are implied by downloading.\n'
                'Dealer pricing, incentives, taxes, fees and availability need human verification.\n')
            for name,key in [('title.txt','title'),('price.txt','price'),('description.txt','description'),
                             ('dealer_link.txt','dealer_vehicle_url')]:
                z.writestr(name,result[key]+'\n')
            z.writestr('photo_urls.txt','\n'.join(result['photo_urls'])+'\n')
            for path,body in photos:
                if not re.fullmatch(r'photos/[0-9]{2,3}\.(?:jpg|png|webp)',path):
                    raise ValueError('unsafe_photo_export_name')
                z.writestr(path,body)
            z.writestr('photo_download_manifest.json',json.dumps({'files':[name for name,_ in photos],
                'downloaded_vehicle_photos':max(0,len(photos)-int(any(name=='photos/02.jpg' for name,_ in photos))),
                'dedication_image_included':any(name=='photos/02.jpg' for name,_ in photos),
                'downloaded_files':len(photos),'expected_vehicle_photos':len(rec['images']),
                'permission_confirmed_by_user':rec['images_approved']},indent=2))
            z.writestr('listing.json',json.dumps(result,ensure_ascii=False,indent=2))
            out=io.StringIO();writer=csv.writer(out)
            writer.writerow(['VIN','Title','Price','Description','Year','Make','Model','Trim','Mileage','Dealer URL','Stock'])
            writer.writerow([result['vin'],result['title'],result['price'],result['description'],result['year'],
                             result['make'],result['model'],result['trim'],result['mileage'],result['dealer_vehicle_url'],result['stock']])
            z.writestr('listing.csv',out.getvalue())
        return buf.getvalue()
