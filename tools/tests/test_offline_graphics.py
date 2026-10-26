import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'offline-assets'))

AVAILABLE=importlib.util.find_spec('PIL') is not None
if AVAILABLE:
    from PIL import Image
    path=Path(__file__).resolve().parents[1]/'offline-assets'/'worker.py'
    spec=importlib.util.spec_from_file_location('sf3_offline_worker',path)
    worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
    sys.modules['worker']=worker
    selection_spec=importlib.util.spec_from_file_location('sf3_pack_selection',path.with_name('select_packs.py'))
    pack_selection=importlib.util.module_from_spec(selection_spec);selection_spec.loader.exec_module(pack_selection)


@unittest.skipUnless(AVAILABLE,'Pillow unavailable: standalone graphics tests not executed')
class OfflineGraphicsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def asset(self):
        image=Image.new('RGBA',(4,2),(248,64,16,255));image.putpixel((3,1),(0,0,0,0))
        raw=image.tobytes();digest=hashlib.sha256(raw).hexdigest();identity='test-material'
        asset=dict(id=identity,width=4,height=2,original_sha256=digest,opaque=False,category='world',
            refs=[dict(category='world',tileable=True)])
        directory=self.root/'assets'/identity;directory.mkdir(parents=True);(directory/'original.rgba').write_bytes(raw)
        return image,asset

    def job(self):
        app=self.root/'app';models=app/'upscaler'/'models';models.mkdir(parents=True)
        (app/'upscaler'/'realesrgan-ncnn-vulkan.exe').write_bytes(b'synthetic executable')
        for suffix in ('bin','param'):(models/('realesr-animevideov3-x4.'+suffix)).write_bytes(b'synthetic model')
        return worker.Job(dict(models=['video'],categories=['world']),self.root,app)

    def fake_gpu(self,job,black=False):
        calls=[]
        def run(command,log,timeout=0):
            calls.append(command);log.parent.mkdir(parents=True,exist_ok=True);log.write_text('synthetic GPU')
            source=Image.open(command[command.index('-i')+1]).convert('RGB')
            output=Image.new('RGB',(4096,4096)) if black else source.resize((4096,4096),Image.Resampling.NEAREST)
            output.save(command[command.index('-o')+1]);return 0
        job.run_process=run
        return calls

    def test_periodic_padding_and_transparent_rgb_fill(self):
        image=Image.new('RGBA',(2,1),(248,0,0,255));image.putpixel((1,0),(0,248,0,255))
        padded=worker.padded_rgb(image,2,True)
        self.assertEqual([padded.getpixel((x,2)) for x in range(6)],[(248,0,0),(0,248,0)]*3)
        image.putpixel((1,0),(0,0,0,0));padded=worker.padded_rgb(image,2,False)
        self.assertTrue(all(p==(248,0,0) for p in padded.getdata()))

    def test_resume_alpha_preservation_and_atomic_pack(self):
        original,asset=self.asset();job=self.job();calls=self.fake_gpu(job)
        catalogs={'revision':dict(scenario=2,profile='synthetic',assets={asset['id']:asset})}
        completed,failures=job.enhance(catalogs);self.assertFalse(failures);self.assertEqual(len(calls),1)
        replacement=Image.open(completed['video']['ready'][asset['id']]/'replacement.png')
        self.assertEqual(replacement.getchannel('A').tobytes(),original.getchannel('A').resize((16,8),Image.Resampling.NEAREST).tobytes())
        completed,_=job.enhance(catalogs);self.assertEqual(len(calls),1,'resume must avoid another GPU call')
        packs=job.pack(catalogs,completed);pack=Path(packs[0]['path'])
        self.assertEqual((pack/asset['id']/'original.rgba').read_bytes(),original.tobytes())
        self.assertEqual((pack/asset['id']/'asset.txt').read_text(),'SF3HDASSET1\n4 2\n16 8\n0 0 1 1\n')
        self.assertFalse(list(pack.glob('*.partial-*')))

    def test_corrupt_cached_output_is_reprocessed(self):
        _,asset=self.asset();job=self.job();calls=self.fake_gpu(job)
        catalogs={'revision':dict(scenario=1,profile='synthetic',assets={asset['id']:asset})}
        completed,_=job.enhance(catalogs)
        (completed['video']['ready'][asset['id']]/'replacement.rgba').write_bytes(b'corrupt')
        job.enhance(catalogs);self.assertEqual(len(calls),2)

    def test_black_gpu_result_not_marked_ready(self):
        _,asset=self.asset();job=self.job();self.fake_gpu(job,black=True)
        result,failures=job.enhance({'r':dict(assets={asset['id']:asset})})
        self.assertTrue(failures);self.assertFalse(result['video']['ready'])

    def test_gpu_timeout_allows_slow_batch_without_invalidating_cache(self):
        _,asset=self.asset();job=self.job();self.fake_gpu(job)
        run=job.run_process;timeouts=[]
        def observed(command,log,timeout):
            timeouts.append(timeout);return run(command,log,timeout)
        job.run_process=observed
        catalog={'r':dict(assets={asset['id']:asset})}
        job.enhance(catalog);self.assertEqual(timeouts,[900])
        job.config['gpu_timeout_seconds']=1200
        job.enhance(catalog)
        self.assertEqual(timeouts,[900],'timeout policy must not discard completed artwork')

    def test_shared_art_does_not_change_disc_categories(self):
        _,asset=self.asset();job=self.job();self.fake_gpu(job)
        other=dict(asset,refs=[dict(category='sprites',file='/CHARACTER.CHR',tileable=False)])
        catalog={'one':dict(assets={asset['id']:asset}),'two':dict(assets={asset['id']:other})}
        before=json.dumps(catalog,sort_keys=True)
        job.enhance(catalog)
        self.assertEqual(json.dumps(catalog,sort_keys=True),before)

    def test_stop_terminates_current_child(self):
        job=self.job();timer=threading.Timer(.4,lambda:job.stop.write_text('stop'))
        timer.start();self.addCleanup(timer.cancel);start=time.monotonic()
        with self.assertRaises(InterruptedError):
            job.run_process([sys.executable,'-c','import time;time.sleep(30)'],self.root/'child.log')
        self.assertLess(time.monotonic()-start,5)

    def test_disc_path_traversal_rejected(self):
        for value in ('/../outside','/dir/../../outside','/C:/outside','/dir\\outside'):
            with self.subTest(value=value),self.assertRaises(ValueError):worker.safe_disc_path(value)

    def test_atomic_receipt_in_long_directory(self):
        parent=self.root/('directory-'+'x'*95);parent.mkdir()
        target=parent/('receipt-'+'a'*64+'.json')
        worker.atomic_json(target,dict(complete=True))
        self.assertEqual(json.loads(target.read_text()),dict(complete=True))
        self.assertFalse(list(parent.glob('.tmp-*')))

    def test_atomic_receipt_retries_temporary_lock(self):
        target=self.root/'status.json';target.write_text('{"old":true}')
        replace=worker.os.replace
        attempts=iter([False,False,True])
        def locked_then_replace(source,destination):
            if not next(attempts):raise PermissionError('locked')
            return replace(source,destination)
        with mock.patch.object(worker.os,'replace',side_effect=locked_then_replace) as operation:
            with mock.patch.object(worker.time,'sleep'):
                worker.atomic_json(target,dict(complete=True))
            self.assertEqual(operation.call_count,3)
        self.assertEqual(json.loads(target.read_text()),dict(complete=True))
        self.assertFalse(list(self.root.glob('.tmp-*')))

    def test_atomic_receipt_permanent_lock_preserves_previous(self):
        target=self.root/'status.json';target.write_text('{"old":true}')
        with mock.patch.object(worker.os,'replace',side_effect=PermissionError('locked')):
            with mock.patch.object(worker.time,'sleep'):
                with self.assertRaises(PermissionError):worker.atomic_json(target,dict(complete=True))
        self.assertEqual(json.loads(target.read_text()),dict(old=True))
        self.assertFalse(list(self.root.glob('.tmp-*')))

    def test_pack_selection_requires_one_revision_and_all_models(self):
        rows=[]
        for model in ('video','anime','general'):
            directory=self.root/model;directory.mkdir()
            row=dict(profile='test-profile',revision='revision',model=model,material_count=1,missing=[],path=str(directory))
            (directory/'manifest.json').write_text(json.dumps(row));rows.append(row)
        selected=pack_selection.selection(rows,'test-profile')
        self.assertEqual(set(selected['models']),{'video','anime','general'})
        with self.assertRaises(ValueError):pack_selection.selection(rows[:2],'test-profile')
        rows[1]['revision']='other'
        with self.assertRaises(ValueError):pack_selection.selection(rows,'test-profile')
        rows[1]['revision']='revision';rows[1]['material_count']=2
        with self.assertRaises(ValueError):pack_selection.selection(rows,'test-profile')


if __name__=='__main__':unittest.main()
