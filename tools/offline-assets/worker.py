"""Local disc -> artwork -> GPU packs. No AI API; first-use CHD setup may download tools."""
import argparse
from collections import Counter, deque
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import time
import uuid

from PIL import Image, ImageStat
from index_packs import build_index

VERSION = 'offline-graphics-1'
MODELS = {'video': 'realesr-animevideov3', 'anime': 'realesrgan-x4plus-anime', 'general': 'realesrgan-x4plus'}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def effective_categories(config):
    selected = set(config.get('categories', ['world', 'backgrounds', 'sprites', 'battle_models']))
    # Older builder GUIs persist the character checkbox as "sprites". Keep those
    # configurations useful while limiting model extraction to its own category.
    if 'sprites' in selected:
        selected.add('battle_models')
    return selected


def decoder_fingerprint(base, filename):
    import battle_textures
    if not battle_textures.supports(filename):
        return base
    return hashlib.sha256((base + ':' + battle_textures.DECODER_VERSION + ':' +
                           sha(Path(battle_textures.__file__))).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name('.tmp-' + uuid.uuid4().hex[:8])
    temp.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    try:
        for attempt in range(21):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                # Windows readers/virus scanners can briefly deny atomic replacement.
                if attempt == 20:
                    raise
                time.sleep(min(.025 * (attempt + 1), .25))
    finally:
        temp.unlink(missing_ok=True)


def external(path):
    path = Path(path).resolve()
    for folder in (path, *path.parents):
        if (folder / '.git').exists():
            raise ValueError('Choose an output folder outside a source repository')
    return path


def safe_disc_path(path):
    parts = PurePosixPath(path.lstrip('/')).parts
    if not parts or any(p in ('.', '..') or ':' in p or '\\' in p for p in parts):
        raise ValueError('Unsafe disc filename: ' + path)
    return Path(*parts)


def padded_rgb(original, padding, repeat):
    """Fill transparent RGB from nearest opaque texels; preserve alpha separately at output."""
    w, h = original.size;data = bytearray(original.tobytes())
    if original.getchannel('A').getextrema() != (255, 255):
        known = bytearray(data[3::4]);pending = deque(i for i, a in enumerate(known) if a)
        while pending:
            i = pending.popleft();x, y = i % w, i // w
            for n in (i-1 if x else -1, i+1 if x+1 < w else -1,
                      i-w if y else -1, i+w if y+1 < h else -1):
                if n >= 0 and not known[n]:
                    data[n*4:n*4+3] = data[i*4:i*4+3];known[n] = 255;pending.append(n)
    source = Image.frombytes('RGBA', (w, h), bytes(data)).convert('RGB')
    # Explicit periodic context for tiled materials; clamp other artwork at its edge.
    out = Image.new('RGB', (w+2*padding, h+2*padding))
    src = source.load();dst = out.load()
    for y in range(out.height):
        sy = (y-padding) % h if repeat else min(max(y-padding, 0), h-1)
        for x in range(out.width):
            sx = (x-padding) % w if repeat else min(max(x-padding, 0), w-1)
            dst[x,y] = src[sx,sy]
    return out


def pages(assets, padding=32, edge=1024):
    page = [];x=y=row=0
    for asset in sorted(assets, key=lambda a: (-a['height'], -a['width'], a['id'])):
        w,h=asset['width']+padding*2,asset['height']+padding*2
        if w>edge or h>edge:
            raise ValueError('Image requires a larger atlas page: ' + asset['id'])
        if x+w>edge:x=0;y+=row;row=0
        if y+h>edge:
            yield page
            page=[];x=y=row=0
        page.append((asset,x,y));x+=w;row=max(row,h)
    if page:yield page


class Job:
    def __init__(self, config, out, app):
        self.config=config;self.out=external(out);self.app=Path(app).resolve();self.started=time.time()
        self.out.mkdir(parents=True,exist_ok=True);self.stop=self.out/'stop.request'
        self.status=self.out/'status.json'

    def check_stop(self):
        if self.stop.exists():raise InterruptedError('Stopped; completed work is cached. Start again to resume.')

    def update(self, phase, message, done=0, total=0, **extra):
        print(message,flush=True)
        atomic_json(self.status,dict(state='running',phase=phase,message=message,completed=done,total=total,
            elapsed_seconds=round(time.time()-self.started),pid=os.getpid(),**extra))

    def run_process(self, command, log, timeout=180):
        self.check_stop();log.parent.mkdir(parents=True,exist_ok=True)
        flags=0x08000000 if os.name=='nt' else 0
        with log.open('wb') as stream:
            process=subprocess.Popen(list(map(str,command)),stdout=stream,stderr=subprocess.STDOUT,creationflags=flags)
            start=time.monotonic()
            try:
                while process.poll() is None:
                    self.check_stop()
                    if time.monotonic()-start>timeout:raise TimeoutError('Local tool timed out; see '+str(log))
                    time.sleep(.2)
                return process.returncode
            except BaseException:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
                raise

    def decode_file(self, extractor, scenario, source, receipt, log, digest, decoder):
        """Try the regular decoder, then the bounded X8PC-only model fallback."""
        try:
            code = self.run_process([extractor, scenario, source, self.out/'assets', receipt], log, 120)
            cached = json.loads(receipt.read_text()) if receipt.exists() else dict(status='failed', images=[])
            if code and cached.get('status') != 'failed':
                cached.update(status='failed', error='Extractor exited ' + str(code))
            import battle_textures
            if battle_textures.supports(source.name) and not cached.get('images') and cached.get('status') in ('unsupported', 'no_images'):
                cached = battle_textures.extract(source, self.out/'assets', receipt, scenario)
                if cached.get('status') == 'unsupported':
                    cached.update(status='failed', error='Recognized X8PC model was not decoded by the battle fallback', images=[])
        except TimeoutError as error:
            cached = dict(status='failed', images=[], error=str(error))
        cached.update(source_sha256=digest, decoder_sha256=decoder)
        atomic_json(receipt, cached)
        return cached

    def inventory(self,sample_files=0):
        sys.path.insert(0,str(self.app/'vendor'))
        from saturnrecomp.disc import Disc, manifest
        from disc_input import resolve_disc
        from disc_profile import identify, content_id
        extractor=self.app/'extractor'/'ExtractAssets.exe'
        decoder=sha(self.app/'extractor'/'ExtractAssets.dll')+sha(self.app/'extractor'/'SF3Lib.dll')
        catalogs={};reports=[]
        for source in self.config['scenarios']:
            self.check_stop();number=int(source['scenario'])
            if number not in (1,2,3,4):raise ValueError('Invalid scenario number')
            self.update('inventory',f"Scenario {number}: hashing and identifying the local disc")
            with (self.out/f'disc-{number}.log').open('a',encoding='utf-8') as log:
                cue=resolve_disc(source['disc'],self.out,self.app/'chdman'/'chdman.exe',log,
                    lambda phase,text:self.update(phase,text))
            disc=Disc(str(cue))
            try:
                contents=manifest(disc);profile_path,profile=identify(disc,contents,self.app/'profiles')
                if int(profile['scenario'])!=number:raise ValueError('Selected disc belongs to a different scenario')
                revision=content_id(contents);folder=self.out/'discs'/revision[:20];folder.mkdir(parents=True,exist_ok=True)
                if (folder/'identity.json').exists() and json.loads((folder/'identity.json').read_text())['content_sha256']!=revision:
                    raise ValueError('Disc cache identity collision; choose a fresh output folder')
                atomic_json(folder/'identity.json',dict(profile=profile_path.name,scenario=number,
                    source=str(source['disc']),cue=str(cue),content_sha256=revision,manifest=contents))
                records=[r for r in disc.iso.walk() if not r.is_dir and not disc.is_cdda(r)]
                records.sort(key=lambda r:(0 if r.path.upper().endswith('.MPD') else 1,r.path))
                catalog={};files=[];requested=0
                for i,record in enumerate(records,1):
                    self.check_stop();relative=safe_disc_path(record.path)
                    name=relative.name.upper();ext=relative.suffix.upper()
                    candidate=ext in ('.MPD','.CHR','.CHP','.DAT','.SPR') or (ext=='.BIN' and name.startswith('X'))
                    if not candidate:
                        files.append(dict(path=record.path,status='not_requested',images=0));continue
                    if sample_files and requested>=sample_files:
                        files.append(dict(path=record.path,status='deferred_sample',images=0));continue
                    requested+=1
                    data=disc.read_file(record);digest=hashlib.sha256(data).hexdigest()
                    extracted=folder/'source'/relative;extracted.parent.mkdir(parents=True,exist_ok=True)
                    if not extracted.exists() or sha(extracted)!=digest:extracted.write_bytes(data)
                    receipt=folder/'receipts'/(hashlib.sha256(record.path.encode()).hexdigest()+'.json')
                    cached=json.loads(receipt.read_text()) if receipt.exists() else {}
                    file_decoder=decoder_fingerprint(decoder,name)
                    valid=cached.get('status')!='failed' and cached.get('source_sha256')==digest and cached.get('decoder_sha256')==file_decoder
                    if valid:
                        for image in cached.get('images',[]):
                            original=self.out/'assets'/image['id']/'original.rgba'
                            if not original.exists() or sha(original)!=image['original_sha256']:valid=False;break
                    if not valid:
                        self.update('extract',f"Scenario {number}: {record.path}",i,len(records))
                        cached=self.decode_file(extractor,number,extracted,receipt,
                            folder/'logs'/(relative.name+'.log'),digest,file_decoder)
                    files.append(dict(path=record.path,status=cached['status'],images=len(cached.get('images',[])),
                        receipt=str(receipt),error=cached.get('error'),warnings=cached.get('warnings',[]),
                        decoder=cached.get('decoder'),textures_decoded=cached.get('textures_decoded')))
                    for image in cached.get('images',[]):
                        asset=catalog.setdefault(image['id'],dict(image,refs=[]))
                        asset['refs'].append(dict(file=record.path,category=image['category'],location=image['location'],
                            tileable=image.get('tileable',False)))
                result=dict(scenario=number,profile=profile_path.name,revision=revision,files=files,
                    unique_images=len(catalog),counts=dict(Counter(x['status'] for x in files)))
                atomic_json(folder/'extraction-report.json',result)
                atomic_json(folder/'catalog.json',list(catalog.values()))
                catalogs[revision]=dict(scenario=number,assets=catalog,profile=profile_path.name)
                reports.append(result)
            finally:
                for handle in disc._fh.values():handle.close()
        atomic_json(self.out/'inventory-report.json',reports)
        return catalogs

    def enhance(self,catalogs,limit=0):
        all_assets={}
        categories=effective_categories(self.config)
        for catalog in catalogs.values():
            for identity,asset in catalog['assets'].items():
                if not any(r['category'] in categories for r in asset['refs']):continue
                if identity not in all_assets:all_assets[identity]=dict(asset,refs=list(asset['refs']))
                else:all_assets[identity]['refs']+=asset['refs']
        assets=list(all_assets.values())
        if limit:assets=assets[:limit]
        model_root=self.app/'upscaler'/'models';completed={};failures=[]
        for short in self.config.get('models',['video']):
            model=MODELS[short]
            weights=sorted(model_root.glob(model+('*-x4.*' if short=='video' else '.*')))
            if not weights:raise ValueError('Missing model weights: '+model)
            signature=hashlib.sha256(json.dumps(dict(version=VERSION,model=model,padding=32,
                upscaler_sha256=sha(self.app/'upscaler'/'realesrgan-ncnn-vulkan.exe'),
                weights={p.name:sha(p) for p in weights}),sort_keys=True).encode()).hexdigest()
            cache=self.out/'enhanced'/signature[:20];cache.mkdir(parents=True,exist_ok=True)
            if (cache/'model.json').exists() and json.loads((cache/'model.json').read_text())['signature']!=signature:
                raise ValueError('Model cache identity collision; choose a fresh output folder')
            atomic_json(cache/'model.json',dict(signature=signature,model=model))
            ready={};pending=[]
            for asset in assets:
                identity=asset['id'];directory=cache/identity;receipt=directory/'ready.json'
                saved=json.loads(receipt.read_text()) if receipt.exists() else {}
                repeat=any(r.get('tileable') for r in asset['refs'])
                if saved.get('original_sha256')==asset['original_sha256'] and saved.get('tileable')==repeat and \
                    (directory/'replacement.rgba').exists() and sha(directory/'replacement.rgba')==saved.get('rgba_sha256'):
                    ready[identity]=directory
                elif asset['width']+64>1024 or asset['height']+64>1024:
                    failures.append(dict(asset=identity,model=short,error='Requires large-image pipeline; retained in inventory'))
                else:pending.append(asset)
            for page_no,entries in enumerate(pages(pending),1):
                self.check_stop();self.update('upscale',f'{model}: GPU page {page_no}, {len(ready)}/{len(assets)} cached images',len(ready),len(assets))
                page=Image.new('RGB',(1024,1024));originals={}
                for asset,x,y in entries:
                    image=Image.frombytes('RGBA',(asset['width'],asset['height']),
                        (self.out/'assets'/asset['id']/'original.rgba').read_bytes())
                    originals[asset['id']]=image
                    page.paste(padded_rgb(image,32,any(r.get('tileable') for r in asset['refs'])),(x,y))
                folder=cache/'pages'/f'{page_no}-{uuid.uuid4().hex[:8]}';folder.mkdir(parents=True)
                before=folder/'input.png';after=folder/'output.png';page.save(before)
                command=[self.app/'upscaler'/'realesrgan-ncnn-vulkan.exe','-i',before,'-o',after,
                    '-m',model_root,'-n',model,'-s','4','-t','64','-g',str(self.config.get('gpu',0)),'-j','1:1:1']
                try:
                    code=self.run_process(command,folder/'gpu.log',max(300,int(self.config.get('gpu_timeout_seconds',900))))
                    log=(folder/'gpu.log').read_text(errors='replace')
                    if code or 'failed' in log.lower():raise ValueError('GPU upscaler failed; original assets retained')
                    enhanced=Image.open(after).convert('RGB');enhanced.load()
                    if enhanced.size!=(4096,4096):raise ValueError('GPU returned the wrong image dimensions')
                    for asset,x,y in entries:
                        self.check_stop();identity=asset['id'];original=originals[identity]
                        crop=enhanced.crop(((x+32)*4,(y+32)*4,(x+32+original.width)*4,(y+32+original.height)*4))
                        a=sum(ImageStat.Stat(original.convert('RGB')).mean);b=sum(ImageStat.Stat(crop).mean)
                        if a>=2 and b<=max(2,a*.1):
                            failures.append(dict(asset=identity,model=short,error='Suspicious black output rejected'));continue
                        crop=crop.convert('RGBA');crop.putalpha(original.getchannel('A').resize(crop.size,Image.Resampling.NEAREST))
                        directory=cache/identity;directory.mkdir(exist_ok=True)
                        crop.save(directory/'replacement.png.tmp',format='PNG');os.replace(directory/'replacement.png.tmp',directory/'replacement.png')
                        data=crop.tobytes();temp=directory/'replacement.rgba.tmp';temp.write_bytes(data);os.replace(temp,directory/'replacement.rgba')
                        atomic_json(directory/'ready.json',dict(original_sha256=asset['original_sha256'],
                            tileable=any(r.get('tileable') for r in asset['refs']),rgba_sha256=hashlib.sha256(data).hexdigest()))
                        ready[identity]=directory
                except (ValueError,TimeoutError,OSError) as error:
                    failures.extend(dict(asset=a['id'],model=short,error=str(error),log=str(folder/'gpu.log')) for a,_,_ in entries)
            completed[short]=dict(ready=ready,signature=signature)
        atomic_json(self.out/'upscale-failures.json',failures)
        return completed,failures

    def pack(self,catalogs,completed):
        reports=[]
        for revision,catalog in catalogs.items():
            for model,cache in completed.items():
                self.update('pack',f"Building Scenario {catalog['scenario']} {model} world-texture pack")
                pack=self.out/'packs'/revision[:20]/model/cache['signature'][:16];pack.mkdir(parents=True,exist_ok=True)
                if (pack/'manifest.json').exists() and json.loads((pack/'manifest.json').read_text())['revision']!=revision:
                    raise ValueError('Pack identity collision; choose a fresh output folder')
                count=0;size=0;missing=[]
                for identity,asset in catalog['assets'].items():
                    self.check_stop()
                    if not any(r['category']=='world' for r in asset['refs']):continue
                    if identity not in cache['ready']:missing.append(identity);continue
                    enhanced=cache['ready'][identity]/'replacement.rgba';original=self.out/'assets'/identity/'original.rgba'
                    target=pack/identity
                    if target.exists():
                        valid=(target/'asset.txt').exists() and (target/'original.rgba').exists() and (target/'replacement.rgba').exists()
                        valid=valid and sha(target/'original.rgba')==asset['original_sha256'] and sha(target/'replacement.rgba')==sha(enhanced)
                        if not valid:raise ValueError('Existing pack material changed; use a new output directory: '+str(target))
                    else:
                        staging=self.out/'staging';staging.mkdir(exist_ok=True)
                        pending=staging/(identity+'.partial-'+uuid.uuid4().hex);pending.mkdir()
                        for source,name in ((original,'original.rgba'),(enhanced,'replacement.rgba')):
                            try:os.link(source,pending/name)
                            except OSError:shutil.copy2(source,pending/name)
                        w,h=asset['width'],asset['height']
                        (pending/'asset.txt').write_text(f'SF3HDASSET1\n{w} {h}\n{w*4} {h*4}\n0 0 1 1\n')
                        atomic_json(pending/'metadata.json',dict(asset,model=model,model_signature=cache['signature']))
                        pending.rename(target)
                    count+=1;size+=enhanced.stat().st_size
                record=dict(scenario=catalog['scenario'],revision=revision,profile=catalog['profile'],model=model,
                    material_count=count,replacement_bytes=size,missing=missing,path=str(pack),
                    scope='World-texture intermediate pack only. Combined packs add CHR/CHP sprites and supported X8PC RGB555 battle-model textures. '
                          'Menus, indexed spell effects, untextured polygons and background planes remain original.')
                atomic_json(pack/'manifest.json',record)
                build_index(pack)
                reports.append(record)
        atomic_json(self.out/'packs-report.json',reports)
        return reports


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--app',type=Path,default=Path(__file__).parent)
    parser.add_argument('--limit',type=int,default=0,help='Diagnostic image limit; zero processes the entire catalog')
    parser.add_argument('--sample-files',type=int,default=0,help='Quick check: decode only this many files per disc')
    parser.add_argument('--inventory-only',action='store_true');args=parser.parse_args()
    if args.limit<0 or args.sample_files<0:parser.error('Sample limits must be nonnegative')
    config=json.loads(args.config.read_text(encoding='utf-8-sig'));job=Job(config,args.out,args.app)
    lock=(job.out/'worker.lock').open('a+b');lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
    try:
        if os.name=='nt':
            import msvcrt;msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl;fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:print('A builder is already running in this output directory.',flush=True);return 2
    job.stop.unlink(missing_ok=True)
    try:
        if any(Path(s['disc']).suffix.lower()=='.chd' for s in config.get('scenarios',[])) and not (args.app/'chdman/chdman.exe').is_file():
            job.update('setup','Preparing the optional CHD tool from its official upstream archive')
            from bootstrap import prepare
            prepare(args.app.resolve().parent,include_chd=True)
        catalogs=job.inventory(args.sample_files)
        if args.inventory_only:
            atomic_json(job.status,dict(state='inventory_complete',phase='complete',message='Inventory complete; no GPU processing requested',pid=os.getpid()));return 0
        completed,failures=job.enhance(catalogs,args.limit);packs=job.pack(catalogs,completed)
        combined=[]
        if effective_categories(config).intersection(('sprites','battle_models')) and not args.sample_files and not args.limit:
            job.update('characters','Assembling indexed world + CHR/CHP sprite + X8PC battle-model texture packs; exact alpha is verified')
            destination=job.out/'playable-packs'/time.strftime('%Y%m%d-%H%M%S')
            command=[sys.executable,'-B',args.app/'character_packs.py','--cache',job.out,'--output',destination]
            for scenario in sorted({int(s['scenario']) for s in config['scenarios']}):command.extend(['--scenario',str(scenario)])
            for model in config.get('models',['video']):command.extend(['--model',model])
            code=job.run_process(command,job.out/'character-packs.log',24*60*60)
            if code:raise ValueError('Character packaging failed; world packs and cache preserved. See character-packs.log')
            combined=json.loads((destination/'packs-report.json').read_text())
            atomic_json(job.out/'playable-packs-report.json',combined)
        extraction=json.loads((job.out/'inventory-report.json').read_text())
        counts=Counter()
        for result in extraction:counts.update(result['counts'])
        gaps=bool(args.limit or args.sample_files or failures) or any(p['missing'] for p in packs+combined) or any(
            x['counts'].get('failed',0) or x['counts'].get('partial',0) or x['counts'].get('unsupported',0) for x in extraction)
        rows=''.join('<tr><td>'+str(p['scenario'])+'</td><td>'+html.escape(p['model'])+'</td><td>'+str(p['material_count'])+
            '</td><td>'+str(len(p['missing']))+'</td><td>'+f"{p['replacement_bytes']/1048576:.1f} MB"+'</td></tr>' for p in packs)
        summary=f'''<!doctype html><meta charset="utf-8"><title>SFIII offline graphics report</title>
<style>body{{font:17px/1.5 system-ui;margin:40px;max-width:1100px;background:#17202b;color:#e6edf5}}td,th{{padding:10px;text-align:left;border-bottom:1px solid #526272}}a{{color:#9bd4ff}}</style>
<h1>SFIII offline graphics report</h1>
<p>{'SAMPLE CHECK — the full catalog has not been processed.' if args.sample_files or args.limit else 'Offline processing finished.'} Packs have not been installed into your game.</p>
<p>Extraction: {counts['extracted']} files decoded; {counts['partial']} partial; {counts['failed']} failed; {counts['unsupported']} unknown candidate formats. GPU failures: {len(failures)}.</p>
<table><tr><th>Scenario</th><th>Style</th><th>World materials ready</th><th>Missing</th><th>Replacement memory</th></tr>{rows}</table>
<p>{'Indexed world + CHR/CHP sprite + supported X8PC battle-model texture packs are ready in playable-packs-report.json. Use Attach packs to game in the builder.' if combined else 'World-texture intermediate packs are ready. A full run with character/model processing also assembles the combined packs.'} Model coverage is limited to decoded RGB555 X8PC textures. Indexed spell effects, untextured polygons and background planes are separate gaps and remain original. Menus remain original. Extraction and processing do not validate every scene, tile seam or animation.</p>
<p><a href="packs-report.json">World-pack paths</a> · <a href="playable-packs-report.json">World + character packs</a> · <a href="inventory-report.json">Extraction report</a> · <a href="upscale-failures.json">GPU failures</a></p>'''
        (job.out/'report.html').write_text(summary,encoding='utf-8')
        atomic_json(job.status,dict(state='complete_with_gaps' if gaps else 'complete',phase='complete',
            message='Quick check finished. Start / Resume runs the full catalog.' if args.sample_files else
                'Offline processing finished. Combined packs cover world, CHR/CHP sprites and supported X8PC textures only. '
                'Review reports for gaps; indexed spell effects and untextured polygons remain original. Packs were not activated.',
            elapsed_seconds=round(time.time()-job.started),pid=os.getpid(),packs=len(packs),character_packs=len(combined),upscale_failures=len(failures),
            sample_file_limit=args.sample_files,sample_image_limit=args.limit))
        return 0
    except (InterruptedError,KeyboardInterrupt):
        atomic_json(job.status,dict(state='stopped',phase='stopped',message='Stopped safely; Start resumes cached work.',pid=os.getpid()));return 0
    except Exception as error:
        import traceback;traceback.print_exc()
        atomic_json(job.status,dict(state='error',phase='error',message=str(error),pid=os.getpid()));return 1
    finally:lock.close()


if __name__=='__main__':raise SystemExit(main())
