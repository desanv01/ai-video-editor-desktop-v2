"""Main-owned native model-store state, integrity and HTTP fault acceptance."""
from __future__ import annotations
import argparse, hashlib, io, json, os, sys, threading, time, unittest, urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
parser=argparse.ArgumentParser();parser.add_argument('--repo',default='.');parser.add_argument('--output',required=True);parser.add_argument('--actual-component');args=parser.parse_args()
repo=Path(args.repo).resolve();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
sys.path.insert(0,str(repo/'backend/app'))
from desktop_native import model_store as module
from desktop_native import model_catalog as catalog
records=[];payload=b'0123456789abcdefghijklmn'
class Response:
 def __init__(self,data=payload,status=200,offset=0,headers=None,url='https://fixture.example/model',gate=None):
  self.body=io.BytesIO(data);self.status=status;self.url=url;self.headers={'Content-Length':str(len(data))}
  if status==206:self.headers['Content-Range']=f'bytes {offset}-{len(payload)-1}/{len(payload)}'
  if headers:self.headers.update(headers)
  self.gate=gate;self.reads=0
 def __enter__(self):return self
 def __exit__(self,*exc):return False
 def geturl(self):return self.url
 def read(self,size):
  self.reads+=1
  if self.gate and self.reads==2:
   self.gate[0].set();assert self.gate[1].wait(10),'Fixture gate timeout'
  return self.body.read(size)
class Cases(unittest.TestCase):
 def setUp(self):
  self.case=out/self._testMethodName;self.case.mkdir();self.component=self.case/'component';self.data=self.case/'data';self.data.mkdir()
  for rel,content in [('bin/whisper-cli.exe',b'Owned runtime fixture'),('models/ggml-small.bin',b'Protected small fixture'),('probes/jfk.wav',b'Public audio fixture')]:
   p=self.component/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
  (self.component/'.verified.json').write_text(json.dumps({'sha256':module.PACK_SHA256,'version':module.PACK_VERSION}))
  self.specs={key:catalog.ModelSpec(key,f'ggml-{key}.bin',len(payload),hashlib.sha256(payload).hexdigest(),f'https://fixture.example/{key}') for key in ['small','medium','large-v3']}
  def lookup(value):
   if value not in self.specs:raise ValueError('Unknown fixture model')
   return self.specs[value]
  self.patches=[patch.object(module,'lookup',side_effect=lookup),patch.object(module,'pinned_catalog',return_value=tuple(self.specs.values())),patch.object(module,'CHUNK',4)]
  for p in self.patches:p.start()
  self.stores=[];self.store=self.new_store();self.probes=[]
  self.probe=patch.object(module.NativeModelStore,'_probe',side_effect=lambda candidate,cancel:self.probes.append(candidate.read_bytes()));self.probe_mock=self.probe.start()
 def new_store(self):
  s=module.NativeModelStore(self.data,self.component,self.component/'bin/whisper-cli.exe',self.component/'models/ggml-small.bin',self.component/'probes/jfk.wav');self.stores.append(s);return s
 def tearDown(self):
  for store in self.stores:store.shutdown()
  self.probe.stop()
  for p in reversed(self.patches):p.stop()
 def wait(self,status,store=None):
  s=store or self.store;deadline=time.monotonic()+10
  while time.monotonic()<deadline:
   job=s.get_job('medium')
   if job and job['status']==status and s._busy is None:return job
   time.sleep(.01)
  self.fail(f'Expected {status}, actual {s.get_job("medium")}')
 def download(self,response,make_active=False):
  opener=SimpleNamespace(open=lambda req,timeout:response)
  with patch.object(module.urllib.request,'build_opener',return_value=opener):
   job=self.store.start_download('medium',make_active=make_active)
   return self.wait('completed' if response.status in [200,206] and response.body.getvalue()==payload and response.url.startswith('https:') else 'failed')
 def part(self,content):
  p=self.store._paths(self.specs['medium'])[1];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content);return p
 def test_pins_and_strict_unknown(self):
  self.assertEqual(catalog.lookup('medium').size_bytes,1533763059);self.assertEqual(catalog.lookup('large-v3').sha256,'64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2')
  with self.assertRaises(ValueError):catalog.lookup('unrecognized')
  self.assertEqual(self.store.selection()['model_id'],'small')
  with self.assertRaises(module.ModelStoreError):self.store.remove('small')
 def test_verified_download_activation_and_restart(self):
  self.download(Response(),True);self.assertEqual(self.probes,[payload]);self.assertEqual(self.store.selection()['model_id'],'medium')
  reopened=self.new_store();self.assertTrue(reopened.selection()['fallback']);reopened.verify_selection();self.assertEqual(reopened.selection()['model_id'],'medium');self.assertEqual(len(self.probes),1)
 def test_range_resume(self):
  self.part(payload[:8]);requests=[]
  def open(req,timeout):requests.append(req.get_header('Range'));return Response(payload[8:],206,8)
  with patch.object(module.urllib.request,'build_opener',return_value=SimpleNamespace(open=open)):
   self.store.start_download('medium');self.wait('completed')
  self.assertEqual(requests,['bytes=8-']);self.assertEqual(self.store._paths(self.specs['medium'])[0].read_bytes(),payload)
 def test_server_200_restarts_instead_of_appending(self):
  self.part(payload[:8]);self.download(Response());self.assertEqual(self.store._paths(self.specs['medium'])[0].read_bytes(),payload)
 def test_server_200_disk_guard_preserves_partial(self):
  part=self.part(payload[:12]);opener=SimpleNamespace(open=lambda req,timeout:Response())
  with patch.object(module.urllib.request,'build_opener',return_value=opener),patch.object(module.shutil,'disk_usage',return_value=SimpleNamespace(free=275)):
   self.store.start_download('medium');job=self.wait('failed')
  self.assertEqual(part.read_bytes(),payload[:12]);self.assertIn('space',job['error'].lower())
 def test_incompatible_range_rejected_without_partial_change(self):
  part=self.part(payload[:8]);opener=SimpleNamespace(open=lambda req,timeout:Response(payload[8:],206,8,{'Content-Range':'bytes 7-23/24'}))
  with patch.object(module.urllib.request,'build_opener',return_value=opener):self.store.start_download('medium');self.wait('failed')
  self.assertEqual(part.read_bytes(),payload[:8]);self.assertFalse(self.probes)
 def test_truncated_transfer_is_retained_unready(self):
  opener=SimpleNamespace(open=lambda req,timeout:Response(payload[:8],headers={'Content-Length':str(len(payload))}))
  with patch.object(module.urllib.request,'build_opener',return_value=opener):self.store.start_download('medium');self.wait('failed')
  self.assertEqual(self.store._paths(self.specs['medium'])[1].read_bytes(),payload[:8]);self.assertEqual(self.store.selection()['model_id'],'small');self.assertFalse(self.probes)
 def test_oversized_transfer_rejected(self):
  opener=SimpleNamespace(open=lambda req,timeout:Response(payload+b'x',headers={'Content-Length':str(len(payload))}))
  with patch.object(module.urllib.request,'build_opener',return_value=opener):self.store.start_download('medium');self.wait('failed')
  self.assertFalse(self.store._paths(self.specs['medium'])[0].exists());self.assertFalse(self.probes)
 def test_hash_mismatch_cannot_probe_or_activate(self):
  opener=SimpleNamespace(open=lambda req,timeout:Response(b'x'*len(payload)))
  with patch.object(module.urllib.request,'build_opener',return_value=opener):self.store.start_download('medium',True);self.wait('failed')
  self.assertFalse(self.probes);self.assertEqual(self.store.selection()['model_id'],'small')
 def test_probe_failure_preserves_previous_active(self):
  self.probe_mock.side_effect=module.ModelStoreError('Controlled runtime incompatibility')
  opener=SimpleNamespace(open=lambda req,timeout:Response())
  with patch.object(module.urllib.request,'build_opener',return_value=opener):self.store.start_download('medium',True);self.wait('failed')
  self.assertEqual(self.store.selection()['model_id'],'small');self.assertFalse(self.store._paths(self.specs['medium'])[2].exists())
 def test_cancel_retain_and_resume(self):
  entered,release=threading.Event(),threading.Event();opener=SimpleNamespace(open=lambda req,timeout:Response(gate=(entered,release)))
  with patch.object(module.urllib.request,'build_opener',return_value=opener):
   self.store.start_download('medium',True);self.assertTrue(entered.wait(10));self.store.cancel('medium');release.set();job=self.wait('paused')
  partial=self.store._paths(self.specs['medium'])[1].read_bytes();self.assertTrue(0<len(partial)<len(payload));self.assertEqual(self.store.selection()['model_id'],'small')
  offset=len(partial);opener=SimpleNamespace(open=lambda req,timeout:Response(payload[offset:],206,offset))
  with patch.object(module.urllib.request,'build_opener',return_value=opener):self.store.start_download('medium',True);self.wait('completed')
  self.assertEqual(self.store.selection()['model_id'],'medium')
 def test_recovered_journal_is_interrupted_without_network(self):
  part=self.part(payload[:8]);now=time.time();spec=self.specs['medium'];job={'schema':1,'id':'780f8390-a1bc-4f46-808b-5b6c53cb2f07','model_id':'medium','sha256':spec.sha256,'status':'downloading','download_url':spec.url,'file_path':str(self.store._paths(spec)[0]),'bytes_downloaded':4,'total_bytes':len(payload),'created_at':now,'updated_at':now}
  self.store._write(self.store._journal('medium'),job)
  with patch.object(module.urllib.request,'build_opener',side_effect=AssertionError('Automatic network forbidden')):reopened=self.new_store()
  self.assertEqual(reopened.get_job('medium')['status'],'interrupted');self.assertEqual(reopened.get_job('medium')['bytes_downloaded'],8)
 def test_leased_model_blocks_removal_and_replacement(self):
  self.download(Response(),True)
  with self.store.usage_lease('medium'):
   with self.assertRaises(module.ModelStoreError):self.store.remove('medium')
   with self.assertRaises(module.ModelStoreError):self.store.start_download('medium')
  self.store.remove('medium');self.assertEqual(self.store.selection()['model_id'],'small');self.assertTrue(self.store.bundled_model.is_file())
 def test_changed_model_invalidates_ready_and_activation(self):
  self.download(Response(),True);file=self.store._paths(self.specs['medium'])[0];file.write_bytes(b'x'*len(payload));self.assertTrue(self.store.selection()['fallback'])
  with self.assertRaises(module.ModelStoreError):self.store.activate('medium')
  self.assertEqual(self.store.selection()['model_id'],'small')
 def test_runtime_change_requires_reprobe(self):
  self.download(Response(),True);self.store.runtime_binary.write_bytes(b'Changed fixture runtime');self.assertTrue(self.store.selection()['fallback']);self.store.activate('medium');self.assertEqual(len(self.probes),2)
 def test_sync_busy_never_returns_absent_download_job(self):
  with self.store._lock:self.store._reserve('medium')
  try:
   with self.assertRaises(module.ModelStoreError):self.store.start_download('medium')
  finally:
   with self.store._lock:self.store._busy=None;self.store._events.clear()
 def test_redirect_and_response_transport_guards(self):
  redirect=module._HTTPSRedirect();req=urllib.request.Request('https://fixture.example/start')
  with self.assertRaises(module.ModelStoreError):redirect.redirect_request(req,None,302,'',{},'http://unsafe.example/')
  self.download(Response(url='http://unsafe.example/'));self.assertFalse(self.probes)

 def reader_failure(self,fail_at):
  from unittest.mock import MagicMock
  proc=SimpleNamespace(stdout=io.BytesIO(b''),stderr=io.BytesIO(b''),returncode=None,poll=lambda:proc.returncode)
  job=MagicMock();real_start=threading.Thread.start;starts=[]
  def start(thread):
   starts.append(thread)
   if len(starts)==fail_at:raise RuntimeError('Controlled reader startup failure')
   return real_start(thread)
  def kill(owned):self.assertIs(owned,proc);proc.returncode=-1
  with patch.object(module.subprocess,'Popen',return_value=proc),patch.object(module,'_WindowsProcessJob',return_value=job),patch.object(module.NativeModelStore,'_kill',side_effect=kill),patch.object(threading.Thread,'start',new=start):
   self.probe.stop()
   try:
    with self.assertRaisesRegex(RuntimeError,'Controlled reader startup failure'):self.store._probe(self.store.bundled_model,threading.Event())
   finally:self.probe.start()
  self.assertEqual(proc.returncode,-1);self.assertTrue(proc.stdout.closed and proc.stderr.closed);self.assertTrue(all(not t.is_alive() for t in starts));self.assertFalse(self.store._threads)
  if os.name=='nt':job.close.assert_called_once();job.resume.assert_not_called()
 def test_first_reader_start_failure_cleans_owned_probe(self):self.reader_failure(1)
 def test_second_reader_start_failure_cleans_started_reader_and_probe(self):self.reader_failure(2)

 def activation_file(self,content=payload):
  file=self.store._paths(self.specs['medium'])[0];file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(content);return file
 def test_sync_qualification_observes_hash_probe_cancel_and_retains_previous(self):
  file=self.activation_file();entered,release=threading.Event(),threading.Event();errors=[]
  def probe(candidate,cancel):
   entered.set();assert release.wait(10);self.store._check(cancel)
  self.probe_mock.side_effect=probe
  def activate():
   try:self.store.activate('medium')
   except BaseException as exc:errors.append(exc)
  thread=threading.Thread(target=activate);thread.start()
  try:
   self.assertTrue(entered.wait(10));job=self.store.get_job('medium');self.assertEqual(job['status'],'probing');self.assertEqual(job['operation'],'qualification');self.assertIsNone(self.store._download_model)
   with self.assertRaises(module.ModelStoreError):self.store.start_download('medium')
   self.assertEqual(self.store.cancel('medium')['status'],'probing')
  finally:release.set();thread.join(10)
  self.assertFalse(thread.is_alive());self.assertIsInstance(errors[0],module._Paused);self.assertEqual(self.store.get_job('medium')['status'],'paused');self.assertEqual(self.store.selection()['model_id'],'small');self.assertEqual(file.read_bytes(),payload)
 def test_sync_qualification_hash_failure_keeps_owned_file_and_selection(self):
  file=self.activation_file(b'x'*len(payload))
  with self.assertRaises(module.ModelStoreError):self.store.activate('medium')
  self.assertEqual(self.store.get_job('medium')['status'],'failed');self.assertEqual(self.store.selection()['model_id'],'small');self.assertFalse(self.probes);self.assertTrue(file.exists())
 def test_sync_missing_model_exposes_failed_job_without_network(self):
  with patch.object(module.urllib.request,'build_opener',side_effect=AssertionError('Activation network forbidden')):
   with self.assertRaises(OSError):self.store.activate('medium')
  self.assertEqual(self.store.get_job('medium')['status'],'failed');self.assertEqual(self.store.get_job('medium')['bytes_downloaded'],0);self.assertEqual(self.store.selection()['model_id'],'small')
 def test_recover_qualification_journal_uses_actual_final_file(self):
  file=self.activation_file();self.store.activate('medium');job=self.store.get_job('medium');job.update(status='verifying',bytes_downloaded=0);self.store._write(self.store._journal('medium'),job)
  with patch.object(module.urllib.request,'build_opener',side_effect=AssertionError('Automatic network forbidden')):reopened=self.new_store()
  self.assertEqual(reopened.get_job('medium')['status'],'interrupted');self.assertEqual(reopened.get_job('medium')['bytes_downloaded'],len(payload));self.assertTrue(reopened.selection()['fallback']);self.assertEqual(file.read_bytes(),payload)

class Result(unittest.TextTestResult):
 def addSuccess(self,test):super().addSuccess(test);records.append({'name':test._testMethodName,'status':'passed'})
 def addFailure(self,test,err):super().addFailure(test,err);records.append({'name':test._testMethodName,'status':'failed','error':self._exc_info_to_string(err,test)})
 def addError(self,test,err):super().addError(test,err);records.append({'name':test._testMethodName,'status':'failed','error':self._exc_info_to_string(err,test)})
result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(unittest.defaultTestLoader.loadTestsFromTestCase(Cases))
if args.actual_component:
 component=Path(args.actual_component).resolve();s=module.NativeModelStore(out/'actual-data',component,component/'bin/whisper-cli.exe',component/'models/ggml-small.bin',component/'probes/jfk.wav');start=time.monotonic()
 try:s._probe(s.bundled_model,threading.Event());records.append({'name':'actual-activated-runtime-CPU-JFK-owned-job-probe','status':'passed','seconds':round(time.monotonic()-start,3)})
 except Exception as exc:records.append({'name':'actual-activated-runtime-CPU-JFK-owned-job-probe','status':'failed','error':str(exc)})
 finally:s.shutdown()
receipt={'status':'passed' if records and all(r['status']=='passed' for r in records) else 'failed','scope':'Production native model store; tiny pinned payload/HTTP/component/probe fixtures for fault/state acceptance, no actual optional model download. Optional actual CPU JFK case uses activated installed pack and new ownership code, no user audio or providers.','cases':records};(out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8');print(json.dumps({'status':receipt['status'],'cases':len(records)}));sys.exit(receipt['status']!='passed')
