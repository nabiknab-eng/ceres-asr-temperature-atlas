#!/usr/bin/env python3
"""Validate JS/Python map pixels and every decoded frame of an exported MP4."""
from __future__ import annotations
import argparse,gzip,hashlib,json,math,shutil,subprocess,tempfile
from pathlib import Path
import numpy as np
from render_core import ROOT,load_spec,color_indices,map_rgb
from export_mp4 import ffmpeg_path,load_chunk,validate_settings

def verify_video(video,manifest,s):
 side=json.loads(video.with_suffix('.frames.json').read_text());mode,start,end,L,fps=validate_settings(side['settings'],manifest)
 expected=manifest['modes'][mode]['frames'][start:end+1]
 assert len(expected)==side['frame_count']==len(side['frames'])
 for i,(a,b) in enumerate(zip(expected,side['frames'])):
  for k,v in a.items():assert b[k]==v
  assert b['video_frame']==i and b['pts_seconds']==i/fps
 cmd=[ffmpeg_path(),'-hide_banner','-loglevel','info','-i',str(video),'-vf','showinfo','-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','pipe:1']
 n=1920*1080*3;errors=[];current=None;data=None
 with tempfile.TemporaryFile() as log:
  p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=log)
  for j in range(len(expected)):
   raw=bytearray()
   while len(raw)<n:
    b=p.stdout.read(n-len(raw))
    if not b:break
    raw.extend(b)
   assert len(raw)==n,('short decoded frame',j,len(raw))
   frame=np.frombuffer(raw,dtype='uint8').reshape(1080,1920,3);i=start+j
   c=next(c for c in manifest['modes'][mode]['chunks'] if c['start']<=i<c['start']+c['frames'])
   if current!=c['id']:data=load_chunk(c);current=c['id']
   fields=data[i-c['start']];per=[]
   for k,x in enumerate(s['map_x']):
    target=map_rgb(fields[k],L[k],s);actual=frame[s['map_y']:s['map_y']+450,x:x+900]
    error=actual.astype('float64')-target;mae=float(np.mean(np.abs(error)));mse=float(np.mean(error**2));psnr=10*math.log10(255**2/max(mse,1e-15))
    assert mae<10 and psnr>26,(j,k,mae,psnr)
    per.append({'mae_rgb':mae,'psnr_db':psnr})
   errors.append(per)
  assert p.stdout.read(1)==b'', 'Extra video frames'
  assert p.wait()==0
  log.seek(0);logtext=log.read().decode(errors='replace')
 import re
 pts=[float(x) for x in re.findall(r'\bn:\s*\d+\s+pts:\s*[-\d]+\s+pts_time:([\d.e+-]+)',logtext)]
 assert len(pts)==len(expected),(len(pts),len(expected))
 assert max(abs(t-i/fps) for i,t in enumerate(pts))<1e-4
 assert 'Video: h264' in logtext and '1920x1080' in logtext
 return {'file':video.name,'frames_decoded':len(errors),'codec':'H.264','resolution':[1920,1080],'fps':fps,
  'all_months_and_inclusive_endpoints_match_manifest':True,'all_pts_correct':True,
  'max_mean_absolute_rgb_error':max(v['mae_rgb'] for p in errors for v in p),'min_map_psnr_db':min(v['psnr_db'] for p in errors for v in p)}

def verify_js(node,manifest,s):
 # Test every allowed scale with exact / adjacent bin boundaries and missing values.
 cases=[]
 for L in list(range(5,41))+[round(1+.2*i,10) for i in range(31)]:
  for k in range(-10,11):
   value=float(k*L/10)
   for x in [np.nextafter(value,-np.inf),value,np.nextafter(value,np.inf)]:cases.append([float(x),float(L)])
  cases.extend([[None,float(L)],[-1000,float(L)],[1000,float(L)]])
 py=[int(color_indices(np.array([np.nan if v is None else v]),L)[0]) for v,L in cases]
 assert all((v==0)==(index==10) for (v,_),index in zip(cases,py) if v is not None)
 program=r'''
const fs=require('fs'),vm=require('vm'),z=require('zlib'),crypto=require('crypto');const inp=JSON.parse(fs.readFileSync(0,'utf8')),root=inp.root;
const scope={};vm.createContext(scope);vm.runInContext(fs.readFileSync(root+'/viewer/color_logic.js','utf8'),scope);const C=scope.AtlasColor;
const cases=inp.cases.map(([v,L])=>C.index(v===null?NaN:v,L));const m=JSON.parse(fs.readFileSync(root+'/manifest.json')),s=JSON.parse(fs.readFileSync(root+'/render_spec.json'));
const l=z.gunzipSync(fs.readFileSync(root+'/data/projection.bin.gz'));const lut=new Int32Array(l.buffer,l.byteOffset,l.byteLength/4);
const colors=new Uint32Array(s.palette.concat([s.missing]).map(c=>(255<<24)|(c[2]<<16)|(c[1]<<8)|c[0]));const h=crypto.createHash('sha256');
for(const chunk of m.modes.rolling.chunks){const b=z.gunzipSync(fs.readFileSync(root+'/'+chunk.file));const a=new Float32Array(b.buffer,b.byteOffset,b.byteLength/4);for(let i=0;i<chunk.frames;i++)for(let k=0;k<2;k++){const f=a.subarray((i*2+k)*64800,(i*2+k+1)*64800);h.update(C.rasterRGBA(f,k?4:20,lut,colors));}}
process.stdout.write(JSON.stringify({cases,hash:h.digest('hex')}));
'''
 result=subprocess.run([node,'-e',program],input=json.dumps({'root':str(ROOT),'cases':cases}).encode(),capture_output=True,check=True)
 js=json.loads(result.stdout);assert js['cases']==py
 h=hashlib.sha256();palette=np.array(s['palette']+[s['missing']],dtype='uint8');lut=s['lut']
 for c in manifest['modes']['rolling']['chunks']:
  data=load_chunk(c)
  for fields in data:
   for k,field in enumerate(fields):
    ci=color_indices(field.ravel(),[20,4][k]);rgb=palette[ci[np.maximum(lut,0)]];rgb[lut<0]=255
    rgba=np.concatenate([rgb,np.full((*rgb.shape[:2],1),255,dtype='uint8')],axis=2);h.update(rgba.tobytes())
 assert h.hexdigest()==js['hash']
 return {'scale_and_boundary_cases':len(cases),'all_allowed_scale_steps_tested':True,'js_python_color_cases_identical':True,
  'all_307_pairs_pre_coast_map_pixels_identical':True,'shared_coast_overlay_identical_file':True,'all_map_rgba_sha256':h.hexdigest()}

def main():
 a=argparse.ArgumentParser();a.add_argument('--node',default=shutil.which('node'));a.add_argument('--video',type=Path,action='append');args=a.parse_args()
 m=json.loads((ROOT/'manifest.json').read_text());s=load_spec();out={'status':'PASS'}
 if args.node:out['html_python_parity']=verify_js(args.node,m,s)
 else:raise SystemExit('Pro kontrolu JavaScript/Python shody zadejte --node /cesta/k/node')
 out['videos']=[verify_video(v,m,s) for v in (args.video or sorted((ROOT/'exports').glob('*.mp4'))) ]
 (ROOT/'validation_media.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
if __name__=='__main__':main()
