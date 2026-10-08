"""Actual managed FFmpeg regressions for Windows subtitle/ASS filter filenames.
Production burn functions, CPU encoding, real audio/video and decoded-frame verification.
"""
import argparse,asyncio,hashlib,json,os,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--ffmpeg-root',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
for k in list(os.environ):
 if k.startswith('AIVE_') or k.endswith('_API_KEY'):os.environ.pop(k,None)
os.environ['RUNTIME_PROFILE']='desktop-native';os.environ['FFMPEG_BINARY_PATH']=str((a.ffmpeg_root/'bin/ffmpeg.exe').resolve());os.environ['FFPROBE_BINARY_PATH']=str((a.ffmpeg_root/'bin/ffprobe.exe').resolve());os.environ['FFMPEG_HARDWARE_ACCELERATION']='cpu'
sys.path[:0]=[str(a.repo/'backend'),str(a.repo/'backend/app')]
from services.ffmpeg import FFmpegService
ffmpeg=os.environ['FFMPEG_BINARY_PATH'];source=a.output/'source.mp4'
subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=black:s=320x180:r=24','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True,capture_output=True)
def pixels(file):return subprocess.run([ffmpeg,'-v','error','-ss','0.5','-i',str(file),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],check=True,capture_output=True).stdout
before=pixels(source);cases=[]
ass='''[Script Info]
ScriptType: v4.00+
PlayResX: 320
PlayResY: 180
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,BRIDGE OVERLAY
'''
async def main():
 for name,kind,folder in [('drive-srt','srt','plain'),('drive-ass','ass','plain'),('punctuation-srt','srt',"teacher's [draft], semicolon; path"),('punctuation-ass','ass',"teacher's [draft], semicolon; path")]:
  directory=a.output/folder;directory.mkdir(exist_ok=True);subtitle=directory/('lecture.'+kind);subtitle.write_text(ass if kind=='ass' else '1\n00:00:00,000 --> 00:00:01,000\nBRIDGE OVERLAY\n',encoding='utf-8');target=a.output/(name+'.mp4')
  try:
   if kind=='ass':await FFmpegService.burn_ass_overlay(str(source),str(subtitle),str(target))
   else:await FFmpegService.burn_subtitles(str(source),str(subtitle),str(target),font_size=20)
   metadata=await FFmpegService.get_video_metadata(str(target));assert metadata['width']==320 and metadata['height']==180;assert abs(metadata['duration']-1)<0.05;assert metadata['has_audio'];after=pixels(target);changed=sum(x!=y for x,y in zip(before,after));assert changed>100,'Burn must visibly alter decoded pixels';cases.append({'name':name,'status':'PASS','changedRgbBytes':changed,'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()});print('PASS '+name,flush=True)
  except Exception as e:
   (a.output/(name+'-failure.txt')).write_text(str(e),encoding='utf-8');cases.append({'name':name,'status':'FAIL','errorType':type(e).__name__});print('FAIL '+name+': '+type(e).__name__,flush=True)
 receipt={'status':'PASS' if all(x['status']=='PASS' for x in cases) else 'FAIL','scope':__doc__.strip(),'cases':cases};(a.output/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8');return receipt['status']=='PASS'
raise SystemExit(0 if asyncio.run(main()) else 1)
