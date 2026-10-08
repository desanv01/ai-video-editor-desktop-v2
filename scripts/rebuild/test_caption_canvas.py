"""Actual burned-caption canvas and safe-margin regression with managed FFmpeg."""
import argparse,asyncio,json,os,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--ffmpeg-root',type=Path,required=True);a=p.parse_args();a.output.mkdir(exist_ok=False,parents=True)
for k in list(os.environ):
 if k.startswith('AIVE_') or k.endswith('_API_KEY'):os.environ.pop(k,None)
os.environ['RUNTIME_PROFILE']='desktop-native';os.environ['FFMPEG_HARDWARE_ACCELERATION']='cpu';os.environ['FFMPEG_BINARY_PATH']=str(a.ffmpeg_root/'bin/ffmpeg.exe');os.environ['FFPROBE_BINARY_PATH']=str(a.ffmpeg_root/'bin/ffprobe.exe')
sys.path[:0]=[str(a.repo/'backend'),str(a.repo/'backend/app')]
from services.ffmpeg import FFmpegService
ff=os.environ['FFMPEG_BINARY_PATH'];cases=[]
async def main():
 for name,width,height,placement in [('landscape720',1280,720,'bottom_center'),('landscape1080',1920,1080,'bottom_center'),('portrait-top-center',720,1280,'top_center'),('portrait-top-left',720,1280,'top_left'),('portrait-top-right',720,1280,'top_right'),('landscape-bottom-left',1280,720,'bottom_left'),('landscape-bottom-right',1280,720,'bottom_right')]:
  try:
   source=a.output/(name+'-source.mp4');target=a.output/(name+'-burned.mp4');subtitle=a.output/(name+'.srt')
   subprocess.run([ff,'-v','error','-f','lavfi','-i',f'color=c=black:s={width}x{height}:r=24','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True,capture_output=True)
   subtitle.write_text('1\n00:00:00,000 --> 00:00:01,000\nThe remote delegates work to the selected device instead\n',encoding='utf-8')
   await FFmpegService.burn_subtitles(str(source),str(subtitle),str(target),font_size=24,placement=placement)
   meta=await FFmpegService.get_video_metadata(str(target));assert(meta['width'],meta['height'])==(width,height);assert meta['has_audio'];assert abs(meta['video_duration']-meta['audio_duration'])<0.1
   pixels=subprocess.run([ff,'-v','error','-ss','0.5','-i',str(target),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],check=True,capture_output=True).stdout
   points=[(i//3%width,i//3//width) for i in range(0,len(pixels),3) if min(pixels[i:i+3])>190];assert points,'Actual visible caption required'
   bounds=[min(x for x,y in points),min(y for x,y in points),max(x for x,y in points),max(y for x,y in points)]
   text_height=bounds[3]-bounds[1]+1;assert 12<=text_height<=28,f'Selected24px caption should fit one line; actual {text_height}px'
   if placement.startswith('bottom'):assert 50<=height-bounds[3]<=80,'Bottom margin must use actual canvas'
   else:assert 35<=bounds[1]<=65,'Top margin must use actual canvas'
   if placement.endswith('center'):assert abs((bounds[0]+bounds[2])/2-width/2)<10,'Center alignment required'
   elif placement.endswith('left'):assert bounds[0]<40,'Left alignment required'
   else:assert width-bounds[2]<40,'Right alignment required'
   cases.append({'name':name,'status':'PASS','whiteTextBounds':bounds,'textHeight':text_height,'audioVideoDrift':abs(meta['video_duration']-meta['audio_duration'])});print('PASS '+name,flush=True)
  except Exception as e:cases.append({'name':name,'status':'FAIL','error':str(e)});print('FAIL '+name+': '+str(e),flush=True)
 receipt={'status':'PASS' if len(cases)==7 and all(x['status']=='PASS' for x in cases) else 'FAIL','scope':__doc__,'cases':cases};(a.output/'receipt.json').write_text(json.dumps(receipt,indent=2));return receipt['status']=='PASS'
raise SystemExit(0 if asyncio.run(main()) else 1)
