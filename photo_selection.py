"""Private, source-specific export selections. Does not modify dealer caches."""
import json,os,re,threading,time,io
from pathlib import Path
from datetime import datetime,timezone
from zipfile import ZipFile,ZIP_DEFLATED
from photo_cache import frame_key,select_export_frames

def atomic_write(path,data):
    tmp=path.with_name(path.name+'.tmp')
    try:
        tmp.write_bytes(data)
        for attempt in range(4):
            try:os.replace(tmp,path);return
            except PermissionError:
                if attempt==3:raise
                time.sleep(.05*(attempt+1))
    finally:
        try:tmp.unlink(missing_ok=True)
        except OSError:pass

def validate_keys(keys):
    if not isinstance(keys,list) or len(keys)>60 or any(not isinstance(k,str) or not 1<=len(k)<=600 for k in keys):raise ValueError('invalid_photo_selection')
    if len(keys)!=len(set(keys)):raise ValueError('duplicate_photo_selection_keys')
    return keys

def safe_name(value):
    return re.sub(r'[^A-Za-z0-9_-]+','_',str(value or '')).strip('_')[:100]

class PhotoSelections:
    def __init__(self,root):
        self.root=Path(root);self.path=self.root/'photo_selection.json';self.lock=threading.RLock()
        try:self.data=json.loads(self.path.read_text())
        except (OSError,ValueError):self.data={}
        if not isinstance(self.data,dict):self.data={}
    def auto_sort_enabled(self):
        with self.lock:return self.data.get('_auto_sort',True) is not False
    def set_auto_sort(self,enabled):
        if not isinstance(enabled,bool):raise ValueError('auto_sort_must_be_boolean')
        with self.lock:
            data=json.loads(json.dumps(self.data));data['_auto_sort']=enabled
            atomic_write(self.path,json.dumps(data,indent=2).encode());self.data=data
        return enabled
    def _id(self,vin,source):
        if not re.fullmatch(r'[A-HJ-NPR-Z0-9]{17}',vin) or source not in ('toyota_used','mitsubishi_used'):raise ValueError('invalid_photo_selection_vehicle')
    def get(self,vin,source,frames):
        self._id(vin,source)
        with self.lock:
            saved=(self.data.get(vin) or {}).get(source)
            available=[frame_key(f) for f in frames];limit=self.data.get('_limit',20)
            if not isinstance(limit,int) or not 1<=limit<=60:limit=20
            keys=saved.get('keys',[]) if isinstance(saved,dict) else available[:2]
            try:validate_keys(keys)
            except ValueError:keys=[]
            return {'keys':[k for k in keys if k in available], 'missing_keys':[k for k in keys if k not in available], 'limit':limit,'saved':saved is not None,'source':source,'groups':{k:v for k,v in saved.get('groups',{}).items() if k in available} if isinstance(saved,dict) else {}}
    def save(self,vin,source,keys,frames,limit=None,groups=None):
        self._id(vin,source);validate_keys(keys)
        available=[frame_key(f) for f in frames]
        if any(k not in available for k in keys):raise ValueError('selection_changed_refresh_preview')
        if limit is not None and (type(limit) is not int or not 1<=limit<=60):raise ValueError('invalid_photo_limit')
        if groups is not None and (not isinstance(groups,dict) or any(v not in ('exterior','interior','unknown') for k,v in groups.items())):raise ValueError('invalid_photo_groups')
        if limit is None:
            cur=self.data.get('_limit',20);limit_eff=cur if type(cur) is int and 1<=cur<=60 else 20
        else:limit_eff=limit
        if len(keys)>limit_eff:raise ValueError(f'too_many_photos_selected; {len(keys)} selected, limit {limit_eff}')
        with self.lock:
            data=json.loads(json.dumps(self.data));data.setdefault(vin,{})[source]={'source':source,'keys':list(keys),'updated':datetime.now(timezone.utc).isoformat()}
            prior_groups=(self.data.get(vin,{}).get(source,{}) or {}).get('groups',{})
            data[vin][source]['groups']={k:v for k,v in (groups if groups is not None else prior_groups).items() if k in available}
            if limit is not None:data['_limit']=limit
            atomic_write(self.path,json.dumps(data).encode());self.data=data
            return self.get(vin,source,frames)
    def folder(self,vin,record):
        stock=safe_name(record.get('stock')) or vin
        # Windows reserved names cannot be folder names.
        if re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]',stock,re.I):stock='stock_'+stock
        folder=self.root/'facebook_photos'/stock
        if folder.is_symlink():raise ValueError('unsafe_photo_folder')
        return folder
    def _write_folder(self,vin,record,selected,report,readme):
        """Publish the folder as one unit: build a staging copy, then swap it in.
        Returns (folder, warning). Never raises: the ZIP must not depend on the folder."""
        import shutil,uuid
        stage=None
        try:
            folder=self.folder(vin,record)
            owner=folder/'.lotradar-owner.json'
            if folder.exists():
                prior=None
                if owner.exists():
                    try:prior=json.loads(owner.read_text()).get('vin')
                    except (OSError,ValueError):prior=None
                if prior!=vin:
                    if prior is None and any(folder.iterdir()):
                        return None,'Folder has files LotRadar did not make; ZIP downloaded, folder not updated.'
                    folder=folder.with_name(folder.name+'_'+vin[-6:])   # stock number reused by another VIN
                    owner=folder/'.lotradar-owner.json'
                    if folder.exists() and owner.exists() and json.loads(owner.read_text()).get('vin')!=vin:
                        return None,'Folder belongs to another vehicle; ZIP downloaded, folder not updated.'
            if folder.is_symlink():raise ValueError('unsafe_photo_folder')
            prior_files=[]
            if folder.exists():
                if not owner.is_file():return None,'Folder has files LotRadar did not make; ZIP downloaded, folder not updated.'
                ownership=json.loads(owner.read_text())
                if ownership.get('vin')!=vin:return None,'Folder belongs to another vehicle; ZIP downloaded, folder not updated.'
                prior_files=ownership.get('files',[])
            folder.parent.mkdir(parents=True,exist_ok=True)
            stage=folder.with_name('.staging-'+folder.name+'-'+uuid.uuid4().hex[:8]);stage.mkdir()
            names=[]
            for name,blob,_ in selected:
                filename=Path(name).name
                if not re.fullmatch(r'\d{2,3}\.(jpg|png|webp)',filename):raise ValueError('invalid_export_frame_name')
                (stage/filename).write_bytes(blob);names.append(filename)
            (stage/'selection.json').write_text(json.dumps(report['files'],indent=2))
            (stage/'README.txt').write_text(readme)
            (stage/'.lotradar-owner.json').write_text(json.dumps({'vin':vin,'files':names}))
            # Keep the user's own files (anything that isn't a numbered export or LotRadar's notes).
            if folder.exists():
                for item in folder.iterdir():
                    if item.name in ('.lotradar-owner.json','selection.json','README.txt') or item.name in prior_files:continue
                    if (stage/item.name).exists():raise ValueError('user_file_conflicts_with_export')
                    if item.is_symlink():os.symlink(os.readlink(item),stage/item.name,target_is_directory=item.is_dir())
                    elif item.is_dir():shutil.copytree(item,stage/item.name,symlinks=True)
                    else:shutil.copy2(item,stage/item.name)
            old=folder.with_name('.old-'+folder.name+'-'+uuid.uuid4().hex[:8])
            try:
                if folder.exists():os.replace(folder,old)
                os.replace(stage,folder)
            except OSError:
                if old.exists() and not folder.exists():os.replace(old,folder)
                shutil.rmtree(stage,ignore_errors=True)
                return None,'A photo in the folder is open in another program; ZIP downloaded, folder not updated. Close it and download again.'
            shutil.rmtree(old,ignore_errors=True)
            return folder,''
        except (OSError,ValueError,TypeError,AttributeError) as exc:
            return None,'Folder not updated ('+type(exc).__name__+'); ZIP downloaded.'
        finally:
            if stage is not None and stage.exists():shutil.rmtree(stage,ignore_errors=True)
    def exported_folder(self,vin):
        name=(self.data.get('_folders') or {}).get(vin)
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,107}',name):return None
        folder=self.root/'facebook_photos'/name
        if folder.is_symlink():return None
        try:
            if json.loads((folder/'.lotradar-owner.json').read_text()).get('vin')==vin:return folder
        except (OSError,ValueError,AttributeError):pass
        return None
    def export(self,vin,source,record,frames,keys,auto_groups=None):
        validate_keys(keys)
        with self.lock:
            limit=self.get(vin,source,frames)['limit']
            groups=(self.data.get(vin,{}).get(source,{}) or {}).get('groups',{})
            from photo_classify import merged_groups
            selected,report=select_export_frames(frames,keys,limit=limit,groups=merged_groups(groups,auto_groups))
            readme=f'Selected {len(selected)} of {len(frames)} photos; files 01..{len(selected)} are in Facebook upload order.\n'
            readme+='Original gallery numbers:\n'+'\n'.join(f"{row['file']} = gallery {row['gallery_number']:02d}" for row in report['files'])
            readme+=f'\nSelected photos no longer available: {len(report["missing_keys"])}.\n'
            buf=io.BytesIO()
            with ZipFile(buf,'w',ZIP_DEFLATED) as z:
                for name,blob,_ in selected:z.writestr(name,blob)
                z.writestr('selection.json',json.dumps(report['files'],indent=2));z.writestr('README.txt',readme)
            folder,warning=self._write_folder(vin,record,selected,report,readme)
            if folder is not None:
                self.data.setdefault('_folders',{})[vin]=folder.name
                try:atomic_write(self.path,json.dumps(self.data).encode())
                except OSError:warning='ZIP and folder updated; folder shortcut could not be saved for restart.'
            report['folder_warning']=warning
            filename='_'.join(safe_name(record.get(k)) for k in ('stock','year','make','model'))+f'_{len(selected)}photos.zip'
            return buf.getvalue(),folder,filename,report
