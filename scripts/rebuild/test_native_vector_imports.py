"""Main: native import isolation and preserved Docker vector boundaries."""
from pathlib import Path
import json,os,subprocess,sys,tempfile,unittest
REPO=Path(sys.argv.pop(1)).resolve() if len(sys.argv)>1 and not sys.argv[1].startswith('-') else Path(__file__).resolve().parents[2]
COMMON="""import sys,importlib.abc,asyncio
from unittest.mock import AsyncMock,patch
sys.path.insert(0,REPO+'/backend/app')
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='qdrant_client' or fullname.startswith('qdrant_client.'):raise BLOCKERROR('QDRANT_IMPORT_BLOCKED')
"""
class VectorImports(unittest.TestCase):
 def exercise(self,case,body):
  parent=REPO/'.test-output/vector-imports';parent.mkdir(parents=True,exist_ok=True)
  with tempfile.TemporaryDirectory(prefix=case+'-',dir=parent) as temp:
   root=Path(temp).resolve();env=os.environ.copy()
   for k in list(env):
    if k.endswith('_API_KEY') or k.startswith('AIVE_') or k in ('DATABASE_URL','DESKTOP_DB_PATH','DESKTOP_VECTOR_ROOT'):env.pop(k,None)
   env.update(RUNTIME_PROFILE='desktop-native' if case=='native' else 'docker',APP_STORAGE_ROOT=str(root/'profile'),AIVE_DESKTOP_DATA_ROOT=str(root/'profile'),DESKTOP_DB_PATH=str(root/'profile/Config/engine.sqlite3'),DESKTOP_VECTOR_ROOT=str(root/'profile/VectorStore'),EMBEDDING_DIMENSIONS='3',APP_DEBUG='false')
   code='REPO='+repr(str(REPO))+'\nBLOCKERROR='+('AssertionError' if case=='native' else 'ImportError')+'\n'+COMMON+body
   result=subprocess.run([sys.executable,'-B','-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=60)
   self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
 def test_native_blocks_qdrant_and_preserves_real_lance_source_lifecycle(self):
  self.exercise('native',"""sys.meta_path.insert(0,Block())
from rag import vector_store as v
assert not any(n=='qdrant_client' or n.startswith('qdrant_client.') for n in sys.modules)
assert v.rag_service._native and v.AsyncQdrantClient is None
from db.database import init_db,dispose_db
async def run():
 await init_db();s=v.rag_service
 with patch.object(s,'_native_configuration',return_value=(object(),'controlled-provider/model/3')),patch.object(s,'_embed_texts',new=AsyncMock(return_value=[[1.,0.,0.]])),patch.object(s,'_embed_batch',new=AsyncMock(return_value=[[1.,0.,0.]])):
  await s.ensure_collection();n=await s.ingest_course_material('owned-source','fixture.txt',[{'page_num':1,'text':'Generic authored teaching concept'}]);assert n==1
  hits=await s.search('Generic',source_id='owned-source',top_k=1);assert len(hits)==1 and hits[0]['source_id']=='owned-source'
  await s.delete_by_source('owned-source');assert not await s.search('Generic',source_id='owned-source')
 await s.close();await dispose_db()
asyncio.run(run())
""")
 def test_docker_retains_actual_qdrant_classes(self):
  self.exercise('docker',"""from rag import vector_store as v
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct
assert v.AsyncQdrantClient is AsyncQdrantClient and v.PointStruct is PointStruct and isinstance(v.rag_service.client,AsyncQdrantClient)
asyncio.run(v.rag_service.client.close())
""")
 def test_docker_missing_dependency_fails_actionably(self):
  self.exercise('missing',"""sys.meta_path.insert(0,Block())
try:from rag import vector_store
except RuntimeError as e:assert str(e)=='qdrant-client is required for the Docker profile'
else:raise AssertionError('Missing Docker dependency must fail')
""")
if __name__=='__main__':unittest.main(verbosity=2)
