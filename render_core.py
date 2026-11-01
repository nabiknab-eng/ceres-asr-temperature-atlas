"""Shared scene specification and exact data-pixel renderer for HTML / H.264 export."""
from __future__ import annotations
import gzip,json,math
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parent

def load_spec(root=ROOT):
 s=json.loads((root/'render_spec.json').read_text());s['lut']=np.frombuffer(gzip.decompress((root/'data/projection.bin.gz').read_bytes()),dtype='<i4').reshape(s['map_height'],s['map_width'])
 s['overlay']=Image.open(root/'viewer/coast.png').convert('RGBA')
 return s

def color_indices(values,limit):
 if not math.isfinite(limit) or limit<=0:raise ValueError('Scale limit must be positive and finite')
 a=np.asarray(values,dtype='float64');ci=np.full(a.shape,10,dtype=np.uint8);good=np.isfinite(a);neg=good&(a<0);pos=good&(a>0)
 ci[neg]=9-np.clip(np.ceil(-a[neg]/limit*10).astype(int)-1,0,9)
 ci[pos]=11+np.clip(np.ceil(a[pos]/limit*10).astype(int)-1,0,9)
 ci[~good]=21
 return ci

def map_rgb(field,limit,s):
 palette=np.array(s['palette']+[s['missing']],dtype='uint8');ci=color_indices(np.asarray(field).ravel(),limit)
 lut=s['lut'];rgb=palette[ci[np.maximum(lut,0)]];rgb[lut<0]=255
 # Opaque coastline pixels are shared, without platform-dependent antialiasing.
 overlay=np.asarray(s['overlay']);rgb[overlay[:,:,3]==255]=overlay[:,:,:3][overlay[:,:,3]==255]
 return rgb

def scene_text(mode,meta,index,total):
 titles={'rolling':'12měsíční klouzavý průměr · krok 1 měsíc','annual':'Kalendářní roční průměr','fiveyear':'Pětiletý průměr ročních anomálií'}
 label=('Střed okna: ' if mode=='rolling' else 'Období: ')+meta['label']
 return {'title':'ASR × povrchová teplota','date':label,'subtitle':titles[mode]+'  |  Reference 2001–2025',
  'window':'Okno: '+meta['window'],'footer':'CERES EBAF Ed4.2.1 × Berkeley Earth High-Resolution TAVG · 1° × 1° · Mollweide · 0°',
  'note':'Šedá: chybějící data nebo neúplná reference. Bílá: přesná nula. Mimo rozsah: krajní barva.',
  'counter':f'Snímek {index+1} / {total}'}

def render_scene(fields,limits,mode,meta,index,total,s,root=ROOT):
 im=Image.new('RGB',(s['width'],s['height']),'white');d=ImageDraw.Draw(im)
 def text(x,y,t,size=24,bold=False,align='left',color='#12232b'):
  f=ImageFont.truetype(str(root/'fonts'/('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')),size)
  d.text((x,y),t,font=f,fill=color,anchor={'left':'ls','center':'ms','right':'rs'}[align])
 texts=scene_text(mode,meta,index,total)
 text(44,64,texts['title'],34,True);text(1876,64,texts['date'],23,False,'right')
 text(44,112,texts['subtitle'],22);d.line((44,145,1876,145),fill='#d8dfe2',width=1)
 for k,(field,limit,x,title,unit) in enumerate(zip(fields,limits,s['map_x'],['Anomálie ASR','Anomálie povrchové teploty'],['W/m²','°C'])):
  text(x,196,title,25,True);text(x+900,196,unit,21,False,'right')
  im.paste(Image.fromarray(map_rgb(field,limit,s)),(x,s['map_y']))
  left=x+190;width=520;y=708
  for j,c in enumerate(s['palette']):
   a=left+math.floor(j*width/21);b=left+math.floor((j+1)*width/21)
   d.rectangle((a,y,b-1,y+17),fill=tuple(c))
  n=f'{limit:g}'.replace('.',',')
  text(left,757,'−'+n+' '+unit,22);text(left+width/2,757,'0',22,False,'center');text(left+width,757,'+'+n+' '+unit,22,False,'right')
 text(44,839,texts['window'],25,True);text(1876,839,texts['counter'],22,False,'right')
 text(44,894,texts['note'],20);d.line((44,952,1876,952),fill='#d8dfe2',width=1)
 text(44,1003,texts['footer'],19)
 return im
