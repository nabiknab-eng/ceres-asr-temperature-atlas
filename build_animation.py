#!/usr/bin/env python3
"""Build the offline viewer and unmodified-value rolling NetCDF from original inputs."""
from __future__ import annotations
import base64, calendar, datetime as dt, gzip, hashlib, importlib.util, json, math, shutil
from pathlib import Path
import numpy as np
from netCDF4 import Dataset, num2date
from PIL import Image, ImageDraw, ImageChops

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('original_reproduce',ROOT/'original/reproduce.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
UTC=dt.timezone.utc

def sha(p): return old.sha256(p)
def monthdate(key): return dt.datetime(*key,1,tzinfo=UTC)
def nextmonth(key):
 y,m=key;return (y+1,1) if m==12 else (y,m+1)
def keys(ds,temperature=False):
 t=old.plain(ds['time'][:])
 if temperature:
  y=np.floor(t).astype(int);m=np.rint((t-y)*12+.5).astype(int)
  np.testing.assert_allclose(t,y+(m-.5)/12,atol=1e-7,rtol=0)
  out=list(zip(y.tolist(),m.tolist()))
 else:
  dates=num2date(t,ds['time'].units,calendar=getattr(ds['time'],'calendar','standard'))
  out=[(x.year,x.month) for x in dates]
 assert len(set(out))==len(out) and out==sorted(out)
 return out
def read_full(path,kind,wanted):
 with Dataset(path) as ds:
  names=('latitude','longitude') if kind=='temperature' else ('lat','lon')
  lat,lon=[old.plain(ds[n][:]) for n in names]
  ki=keys(ds,kind=='temperature');idx=np.array([ki.index(k) for k in wanted])
  assert [ki[i] for i in idx]==wanted
  arrays=[]
  for n in (['temperature'] if kind=='temperature' else ['solar_mon','toa_sw_all_mon']):
   v=ds[n];sl=[slice(None)]*3;sl[v.dimensions.index('time')]=idx
   a=old.plain(v[tuple(sl)]);a=np.transpose(a,[v.dimensions.index(n) for n in ('time',*names)])
   for attr,op in [('valid_min',np.less),('valid_max',np.greater)]:
    if hasattr(v,attr):a[op(a,float(v.getncattr(attr)))]=np.nan
   a[~np.isfinite(a)]=np.nan;arrays.append(a)
  ilat=np.argsort(lat);lon=(lon+180)%360-180;ilon=np.argsort(lon)
  np.testing.assert_allclose(lat[ilat],old.LAT,atol=1e-9,rtol=0)
  np.testing.assert_allclose(lon[ilon],old.LON,atol=1e-9,rtol=0)
  a=arrays[0] if kind=='temperature' else arrays[0]-arrays[1]
  return a[:,ilat,:][:,:,ilon]

def chunk_file(name,arr):
 raw=np.asarray(arr,dtype='<f4').tobytes(order='C')
 zipped=gzip.compress(raw,compresslevel=6,mtime=0)
 (ROOT/'data'/f'{name}.bin.gz').write_bytes(zipped)
 (ROOT/'viewer'/f'{name}.js').write_text('Atlas.register('+json.dumps(name)+','+json.dumps(base64.b64encode(zipped).decode())+');\n')
 return {'id':name,'script':f'viewer/{name}.js','file':f'data/{name}.bin.gz','frames':len(arr),'sha256':hashlib.sha256(raw).hexdigest()}

def projection():
 w,h=900,450;s=math.sqrt(2)
 x=(np.arange(w)+.5)/w*(4*s)-2*s;y=s-(np.arange(h)+.5)/h*(2*s)
 xx,yy=np.meshgrid(x,y);inside=(xx/(2*s))**2+(yy/s)**2<=1
 theta=np.arcsin(yy/s);phi=np.arcsin(np.clip((2*theta+np.sin(2*theta))/np.pi,-1,1))
 lam=np.pi*xx/(2*s*np.cos(theta))
 iy=np.clip(np.floor(np.rad2deg(phi)+90).astype(int),0,179)
 ix=np.clip(np.floor(np.rad2deg(lam)+180).astype(int),0,359)
 lut=np.where(inside,iy*360+ix,-1).astype('<i4')
 assert lut[225,0]//360 in (89,90) and lut[225,-1]//360 in (89,90)
 assert lut[225,0]%360==0 and lut[225,-1]%360==359
 assert lut[0,w//2]//360==179 and lut[-1,w//2]//360==0
 raw=lut.tobytes();packed=gzip.compress(raw,mtime=0)
 (ROOT/'data/projection.bin.gz').write_bytes(packed)
 overlay=Image.new('RGBA',(w,h));draw=ImageDraw.Draw(overlay)
 for line in old.projected_coast():
  coords=[((float(a)+2*s)/(4*s)*w-.5,(s-float(b))/(2*s)*h-.5) for a,b in line]
  draw.line(coords,fill=(0,0,0,255),width=1)
 mask=Image.fromarray((inside*255).astype('uint8'))
 overlay.putalpha(ImageChops.multiply(overlay.getchannel('A'),mask))
 # Outline only; no political borders or graticule.
 draw=ImageDraw.Draw(overlay);draw.ellipse((0,0,w-1,h-1),outline=(0,0,0,255),width=1)
 overlay.save(ROOT/'viewer/coast.png')
 out={'width':1920,'height':1080,'map_width':w,'map_height':h,'map_x':[44,976],'map_y':224,
      'palette':old.PALETTE.tolist(),'missing':[210,214,220],
      'projection_sha256':hashlib.sha256(raw).hexdigest(),
      'projection_gzip':base64.b64encode(packed).decode(),
      'coast_png':base64.b64encode((ROOT/'viewer/coast.png').read_bytes()).decode()}
 return out

def main():
 ceres=ROOT/'original/raw'/old.CERES;temp=ROOT/'original/raw'/old.BERKELEY
 with Dataset(ceres) as d:ck=keys(d)
 with Dataset(temp) as d:tk=keys(d,True)
 common=sorted(set(ck)&set(tk));assert common
 # Global gaps are rejected, never bridged by a 12-element moving window.
 assert all(nextmonth(a)==b for a,b in zip(common,common[1:]))
 days=np.array([calendar.monthrange(*k)[1] for k in common],dtype=np.float64)
 frames=[]
 for i in range(len(common)-11):
  start=monthdate(common[i]);end=monthdate(nextmonth(common[i+11]));middle=start+(end-start)/2
  frames.append({'index':i,'label':middle.strftime('%d.%m.%Y %H:%M UTC'),'center':middle.isoformat(),
   'start':start.isoformat(),'end_exclusive':end.isoformat(),
   'window':f'{common[i][1]:02d}/{common[i][0]} – {common[i+11][1]:02d}/{common[i+11][0]}','days':int(days[i:i+12].sum())})
 annual=[];five=[];rolling=[];report={}
 annual_ds=Dataset(ROOT/'original/data/annual_anomalies_2001-2025.nc')
 five_ds=Dataset(ROOT/'original/data/five_year_anomalies_2001-2025.nc')
 ref_ds=Dataset(ROOT/'original/data/reference_fields_2001-2025.nc')
 for kind,path in [('asr',ceres),('temperature',temp)]:
  print('Read',kind,flush=True);a=read_full(path,kind,common)
  ref=old.plain(ref_ds[kind+'_reference'][:]);r=[];counts=[]
  for i in range(len(frames)):
   b=a[i:i+12];weights=days[i:i+12,None,None]
   counts.append(np.isfinite(b).sum(axis=0).astype('uint8'))
   r.append(np.sum(b*weights,axis=0)/weights.sum()-ref)
  r=np.array(r);counts=np.array(counts);rolling.append(r)
  ann=old.plain(annual_ds[kind+'_anomaly'][:]);annual.append(ann)
  five.append(old.plain(five_ds[kind+'_anomaly'][:]))
  # Recompute the legacy reference independently from the extended monthly input.
  ridx=[common.index((y,m)) for y in range(2001,2026) for m in range(1,13)]
  aa,rr,an,_,_=old.annual_reference(a[ridx]);np.testing.assert_allclose(rr,ref,atol=1e-10,rtol=0,equal_nan=True)
  np.testing.assert_allclose(an,ann,atol=1e-10,rtol=0,equal_nan=True)
  # Independent nested scalar weighted average, including NaN propagation.
  max_error=0.
  for i in sorted(set([0,1,9,10,11,12,60,120,180,240,len(frames)-1])):
   for iy,ix in [(0,0),(179,359),(90,180),(100,120),(150,300),(170,55)]:
    total=0.;denom=0.
    for j in range(i,i+12):total+=float(a[j,iy,ix])*float(days[j]);denom+=float(days[j])
    expected=total/denom-ref[iy,ix];actual=r[i,iy,ix]
    assert np.isnan(expected)==np.isnan(actual)
    if np.isfinite(expected):max_error=max(max_error,abs(actual-expected))
  assert max_error<1e-10
  # Jan-Dec windows must reproduce EVERY original annual grid exactly.
  for y in range(2001,2026):
   i=common.index((y,1));np.testing.assert_allclose(r[i],ann[y-2001],atol=1e-10,rtol=0,equal_nan=True)
  f32=r.astype('float32').astype('float64');finite=np.isfinite(r)
  report[kind]={'scalar_weighted_mean_max_error':max_error,'original_reference_loaded_without_recomputation':True,
   'recomputed_reference_max_error':float(np.nanmax(np.abs(rr-ref))),
   'recomputed_annual_anomaly_max_error':float(np.nanmax(np.abs(an-ann))),
   'max_float32_display_error':float(np.max(np.abs(f32[finite]-r[finite]))),
   'rolling_max_abs':float(np.nanmax(np.abs(r))),'incomplete_window_cells':int(np.sum(counts<12)),
   'missing_reference_cells':int(np.sum(~np.isfinite(ref))),'source_sha256':sha(path)}
  # Full precision results, no clipping and no shortened missing-value denominators.
  ncpath=ROOT/'data/rolling_anomalies.nc'
  with Dataset(ncpath,'w' if kind=='asr' else 'a') as nc:
   if kind=='asr':
    nc.createDimension('time',len(frames));nc.createDimension('lat',180);nc.createDimension('lon',360);nc.createDimension('bounds',2)
    for n,v in [('lat',old.LAT),('lon',old.LON)]:nc.createVariable(n,'f8',(n,))[:]=v
    nc['lat'].units='degrees_north';nc['lon'].units='degrees_east'
    t=nc.createVariable('time','f8',('time',));t.units='days since 1970-01-01 00:00:00';t.calendar='proleptic_gregorian';t.bounds='time_bounds'
    epoch=dt.datetime(1970,1,1,tzinfo=UTC)
    t[:]=[(dt.datetime.fromisoformat(f['center'])-epoch).total_seconds()/86400 for f in frames]
    nc.createVariable('time_bounds','f8',('time','bounds'))[:]=[[(dt.datetime.fromisoformat(f[k])-epoch).total_seconds()/86400 for k in ['start','end_exclusive']] for f in frames]
    nc.Conventions='CF-1.10';nc.reference_period='2001-2025'
    nc.reference_aggregation='unchanged arithmetic mean of 25 day-weighted complete calendar years'
    nc.rolling_aggregation='12 consecutive common months; Gregorian day weights; complete 12-month cells only'
    nc.time_center='exact midpoint of start-inclusive and next-month-start-exclusive window bounds (UTC)'
    nc.missing_policy='NaN propagates from any missing month or missing fixed reference'
    nc.input_months=json.dumps(common);nc.source_sha256=json.dumps({'asr':sha(ceres),'temperature':sha(temp)})
   v=nc.createVariable(kind+'_anomaly','f8',('time','lat','lon'),zlib=True,complevel=5,shuffle=True,fill_value=np.nan);v[:]=r
   v.units='W m-2' if kind=='asr' else 'degree_Celsius';v.cell_methods='time: mean (weighted by actual days in month)'
   nc.createVariable(kind+'_valid_months','u1',('time','lat','lon'),zlib=True)[:]=counts
   nc.createVariable(kind+'_reference','f8',('lat','lon'),zlib=True,fill_value=np.nan)[:]=ref
  del a
 for d in (annual_ds,five_ds,ref_ds):d.close()
 modes={}
 for name,arrays,metas in [('annual',annual,[{'index':i,'label':str(y),'window':f'01/{y} – 12/{y}','center':(monthdate((y,1))+(monthdate((y+1,1))-monthdate((y,1)))/2).isoformat()} for i,y in enumerate(range(2001,2026))]),
  ('fiveyear',five,[{'index':i,'label':f'{s}–{s+4}','window':f'01/{s} – 12/{s+4}','center':(monthdate((s,1))+(monthdate((s+5,1))-monthdate((s,1)))/2).isoformat()} for i,s in enumerate(range(2001,2026,5))]),('rolling',rolling,frames)]:
  data=np.stack(arrays,axis=1);chunks=[]
  for i in range(0,len(data),12):
   c=chunk_file(f'{name}-{i//12:03d}',data[i:i+12]);c['start']=i;chunks.append(c)
  maxima=np.nanmax(np.abs(data),axis=(0,2,3));auto=[max(5,min(40,math.ceil(maxima[0]))),max(1,min(7,math.ceil(maxima[1]*5)/5))]
  modes[name]={'frames':metas,'chunks':chunks,'max_abs':maxima.tolist(),'auto_limits':auto}
  print(name,len(data),'auto',auto,flush=True)
 render=projection();(ROOT/'render_spec.json').write_text(json.dumps(render,ensure_ascii=False))
 payload={'schema':1,'grid':{'lat':180,'lon':360,'lat_first':-89.5,'lon_first':-179.5},'reference':'2001–2025',
  'common_start':f'{common[0][0]}-{common[0][1]:02d}','common_end':f'{common[-1][0]}-{common[-1][1]:02d}',
  'modes':modes,'render':render,'temperature_product':'Berkeley Earth High-Resolution global TAVG; official 1°; air anomalies over sea ice'}
 (ROOT/'manifest.json').write_text(json.dumps({k:v for k,v in payload.items() if k!='render'},ensure_ascii=False,indent=2))
 (ROOT/'viewer/manifest.js').write_text('window.ATLAS_MANIFEST='+json.dumps(payload,ensure_ascii=False,separators=(',',':'))+';\n')
 report.update({'status':'PASS','common_months':len(common),'rolling_frames':len(frames),'first_window':frames[0],'last_window':frames[-1],
  'projection':old.projection_checks(),'time_alignment':'identical common YYYY-MM keys selected explicitly in each source',
  'complete_global_month_sequence':True,'original_annual_and_fiveyear_files_unchanged':True})
 (ROOT/'validation_computation.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
 import matplotlib
 fontdir=Path(matplotlib.get_data_path())/'fonts/ttf'
 for f in ['DejaVuSans.ttf','DejaVuSans-Bold.ttf']:shutil.copy2(fontdir/f,ROOT/'fonts'/f)
 import imageio_ffmpeg
 binary=Path(imageio_ffmpeg.get_ffmpeg_exe());shutil.copy2(binary,ROOT/'bin/ffmpeg-macos-arm64')
 shutil.copy2(Path(imageio_ffmpeg.__file__).parent/'binaries/README.md',ROOT/'bin/FFMPEG_README.md') if (Path(imageio_ffmpeg.__file__).parent/'binaries/README.md').exists() else None
 print('BUILD PASS',flush=True)
if __name__=='__main__':main()
