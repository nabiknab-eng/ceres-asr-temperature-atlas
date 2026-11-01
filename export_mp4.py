#!/usr/bin/env python3
"""Offline H.264 / MP4 export; same float32 display data, LUT and palette as HTML."""
from __future__ import annotations
import argparse,base64,gzip,json,math,os,platform,shutil,subprocess,sys,tempfile
from pathlib import Path
import numpy as np
from render_core import ROOT,load_spec,render_scene

def ffmpeg_path(root=ROOT):
 if os.environ.get('FFMPEG_BINARY'):return os.environ['FFMPEG_BINARY']
 if platform.system()=='Darwin' and platform.machine()=='arm64' and (root/'bin/ffmpeg-macos-arm64').exists():return str(root/'bin/ffmpeg-macos-arm64')
 if shutil.which('ffmpeg'):return shutil.which('ffmpeg')
 try:
  import imageio_ffmpeg
  return imageio_ffmpeg.get_ffmpeg_exe()
 except ImportError:raise SystemExit('FFmpeg chybí. Nainstalujte závislosti podle README.md.')

def validate_settings(settings,manifest):
 if settings.get('schema')!=1:raise ValueError('Unsupported settings schema')
 mode=settings.get('mode','rolling')
 if mode not in manifest['modes']:raise ValueError('Unknown mode')
 n=len(manifest['modes'][mode]['frames']);start=int(settings.get('start',0));end=int(settings.get('end',n-1))
 if not 0<=start<=end<n:raise ValueError('Invalid inclusive frame interval')
 limits=[float(settings['asr_limit']),float(settings['temperature_limit'])];fps=float(settings.get('fps',6))
 if not 5<=limits[0]<=40 or abs(limits[0]-round(limits[0]))>1e-8:raise ValueError('ASR range must be integer 5…40')
 if not 1<=limits[1]<=7 or abs(limits[1]*5-round(limits[1]*5))>1e-8:raise ValueError('Temperature range must be 1…7, step 0.2')
 if not math.isfinite(fps) or not .25<=fps<=60:raise ValueError('FPS must be 0.25…60')
 return mode,start,end,limits,fps

def load_chunk(chunk,root=ROOT):
 import hashlib
 binary=root/chunk['file']
 if binary.exists():packed=binary.read_bytes()
 else:
  # Compact distribution uses the exact same packed local JS payload as HTML.
  source=(root/chunk['script']).read_text()
  prefix='Atlas.register('+json.dumps(chunk['id'])+','
  if not source.startswith(prefix) or not source.endswith(');\n'):raise ValueError('Invalid local chunk wrapper')
  packed=base64.b64decode(json.loads(source[len(prefix):-3]),validate=True)
 raw=gzip.decompress(packed)
 if hashlib.sha256(raw).hexdigest()!=chunk['sha256']:raise ValueError('Chunk checksum failed: '+chunk['file'])
 return np.frombuffer(raw,dtype='<f4').reshape(chunk['frames'],2,180,360)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--settings',type=Path);p.add_argument('--output',type=Path);p.add_argument('--preview',type=Path);p.add_argument('--frame',type=int);p.add_argument('--crf',type=int,default=16);args=p.parse_args()
 if not args.settings:args.settings=ROOT/'export_settings.json'
 settings=json.loads(args.settings.read_text());manifest=json.loads((ROOT/'manifest.json').read_text())
 mode,start,end,limits,fps=validate_settings(settings,manifest);s=load_spec();m=manifest['modes'][mode]
 if args.frame is not None:start=end=args.frame
 if not 0<=start<=end<len(m['frames']):raise ValueError('Frame out of bounds')
 def generate():
  current=None;data=None
  for i in range(start,end+1):
   chunk=next(c for c in m['chunks'] if c['start']<=i<c['start']+c['frames'])
   if current!=chunk['id']:data=load_chunk(chunk);current=chunk['id']
   fields=data[i-chunk['start']]
   yield i,render_scene(fields,limits,mode,m['frames'][i],i,len(m['frames']),s)
 if args.preview:
  _,im=next(generate());im.save(args.preview);return
 output=(args.output or ROOT/'exports'/f'{mode}_{start:03d}-{end:03d}_{fps:g}fps.mp4').resolve();output.parent.mkdir(parents=True,exist_ok=True)
 if output.exists():raise FileExistsError(f'Výstup už existuje: {output}. Zvolte jiné jméno.')
 if not 0<=args.crf<=40:raise ValueError('CRF out of range')
 # Constant frame rate. Each input frame appears exactly once, including both ends.
 cmd=[ffmpeg_path(),'-hide_banner','-loglevel','warning','-nostdin','-n','-f','rawvideo','-pixel_format','rgb24','-video_size','1920x1080','-framerate',str(fps),'-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf',str(args.crf),'-pix_fmt','yuv420p','-movflags','+faststart','-metadata','comment=Monthly steps; fixed reference 2001-2025; see adjacent frame manifest',str(output)]
 with tempfile.TemporaryFile() as log:
  process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
  try:
   for i,im in generate():
    process.stdin.write(im.tobytes())
    if i==start or (i-start+1)%12==0 or i==end:print(f'Export {i-start+1}/{end-start+1}: {m["frames"][i]["label"]}',flush=True)
   process.stdin.close();code=process.wait()
  except BaseException:
   process.kill();process.wait();raise
  if code:
   log.seek(0);raise RuntimeError(log.read().decode(errors='replace'))
 frame_manifest={'schema':1,'video':output.name,'codec':'H.264','pixel_format':'yuv420p','width':1920,'height':1080,'fps':fps,'frame_count':end-start+1,'settings':settings,
  'reference':'2001-2025','frames':[{'video_frame':j,'pts_seconds':j/fps,**m['frames'][i]} for j,i in enumerate(range(start,end+1))],
  'rendering':'identical little-endian float32 display fields, projection LUT, palette and opaque coast overlay as HTML; MP4 is lossy H.264'}
 output.with_suffix('.frames.json').write_text(json.dumps(frame_manifest,ensure_ascii=False,indent=2))
 print('HOTOVO:',output,flush=True)
if __name__=='__main__':main()
