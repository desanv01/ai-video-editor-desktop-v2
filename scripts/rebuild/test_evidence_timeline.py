"""Main-owned supporting evidence consistency with canonical current editing decisions."""
import argparse,json,sys
from pathlib import Path
from types import SimpleNamespace
parser=argparse.ArgumentParser();parser.add_argument('--repo',default='.');parser.add_argument('--output',required=True);args=parser.parse_args();repo=Path(args.repo).resolve();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False);sys.path.insert(0,str(repo/'backend/app'))
from services.export_artifacts import build_timeline_decision_rows
from services.transcript_edit_decisions import create_transcript_cut_decision,build_synced_timeline_plan
cases=[]
def segment(start=0,end=5,stored=4,action='keep'):
 return SimpleNamespace(id='owned-segment',segment_index=0,start_time=start,end_time=end,duration=stored,action=action,teacher_action='keep' if action=='keep' else None,is_teacher_modified=action=='keep',teacher_note='Original teacher note',topic_label='Owned fixture',summary='Generic teaching',action_confidence=.9,action_reason='Original AI reason')
def test(name,fn):
 try:fn();cases.append({'name':name,'status':'passed'})
 except Exception as e:cases.append({'name':name,'status':'failed','error':str(e)})
 print(cases[-1])
def rows(segments,cut=None):
 plan=SimpleNamespace(plan_json={},original_duration=5,estimated_duration=5)
 if cut:create_transcript_cut_decision(plan=plan,timeline_words=[{'text':'generic','start_time':cut[0],'end_time':cut[1]}],word_start_index=0,word_end_index=0)
 actual=build_timeline_decision_rows(segments=segments,plan_payload=plan.plan_json,quality_report={'original_duration_seconds':5})
 return actual[0],plan

def span():
 row,_=rows([segment(0,36.5,27.7)]);assert row['duration_seconds']==36.5,f"Source span0..36.5 reported {row['duration_seconds']}";assert row['stored_duration_seconds']==27.7
 assert row['teacher_note']=='Original teacher note' and row['ai_reason']=='Original AI reason'
def unchanged():
 seg=segment();row,plan=rows([seg]);expected=build_synced_timeline_plan(plan=plan,segments=[seg],duration_seconds=5)['playable_ranges'];assert json.loads(row['output_ranges_json'])==expected,'Included segment must report its actual canonical output range'
def partial():
 seg=segment();row,plan=rows([seg],(2,3));expected=build_synced_timeline_plan(plan=plan,segments=[seg],duration_seconds=5)['playable_ranges'];assert json.loads(row['output_ranges_json'])==expected and len(expected)==2;assert row['included_in_output']
def zero():
 row,_=rows([segment()],(0,5));assert not row['included_in_output'],'A teacherKEEP segment entirely cut by current transcript decisions must not claim inclusion';assert json.loads(row['output_ranges_json'])==[]
def cut():
 row,_=rows(iter([segment(action='cut')]));assert not row['included_in_output'] and json.loads(row['output_ranges_json'])==[]
for name,fn in [('current-source-span-and-stored-speech-duration-distinguished',span),('included-segment-has-canonical-output-range',unchanged),('word-cut-splits-output-ranges-exactly',partial),('all-word-cut-is-not-included-despite-segment-keep',zero),('teacher-segment-cut-and-iterator-input-preserved',cut)]:test(name,fn)
receipt={'status':'passed' if all(x['status']=='passed' for x in cases) else 'failed','scope':'Actual supporting-export helper versus shared canonical timeline, preserving AI/teacher provenance; tiny fixtures, no DB/provider/render calls.','cases':cases};(out/'receipt.json').write_text(json.dumps(receipt,indent=2));sys.exit(receipt['status']!='passed')
