#!/usr/bin/env python3
"""Reproduce the offline atlas from unchanged spatial NetCDF inputs.

Run: python reproduce.py [--download] [--skip-maps]
No image AI, contour interpolation, smoothing or geographical upsampling.
"""
from __future__ import annotations
import argparse, base64, calendar, hashlib, json, math, os, sys, zipfile
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR', str(Path(__file__).parent / '.mpl-cache'))
import numpy as np
import xarray as xr
from netCDF4 import Dataset, num2date
from pyproj import Proj
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import Ellipse
import shapefile

ROOT = Path(__file__).resolve().parent
YEARS = np.arange(2001, 2026)
PERIODS = [(start, start+4) for start in range(2001,2026,5)]
COLOR_LIMITS = {'asr':20., 'temperature':4.}
LAT = np.arange(-89.5, 90, 1.)
LON = np.arange(-179.5, 180, 1.)
CERES = 'CERES_EBAF-TOA_Edition4.2.1_200003-202608.nc'
BERKELEY = 'Global_TAVG_Gridded_1deg.nc'
URLS = {
 CERES: 'https://data.asdc.earthdata.nasa.gov/asdc-prod-protected/CERES/CERES_EBAF-TOA_Edition4.2.1/' + CERES,
 BERKELEY: 'https://storage.googleapis.com/berkeley-earth-temperature-hr/global/gridded/' + BERKELEY,
 'ne_50m_coastline.zip': 'https://naturalearth.s3.amazonaws.com/50m_physical/ne_50m_coastline.zip',
}
MOLL = Proj('+proj=moll +lon_0=0 +R=1 +units=m +no_defs')
SQ2 = math.sqrt(2)
# Ten distinct shades per sign. White belongs only to exactly zero.
NEG = np.rint(np.linspace([18, 61, 131], [235, 243, 250], 10)).astype('uint8')
POS = np.rint(np.linspace([252, 237, 233], [164, 24, 43], 10)).astype('uint8')
PALETTE = np.vstack([NEG, [255, 255, 255], POS]).astype('uint8')

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()

def download_inputs(include_ceres=True):
    import requests
    for name, url in URLS.items():
        if name==CERES and not include_ceres: continue
        dest = ROOT / 'raw' / name
        if dest.exists(): continue
        print('Downloading', name, flush=True)
        tmp = dest.with_suffix(dest.suffix + '.part')
        with requests.get(url, stream=True, timeout=(30, 300)) as r:
            r.raise_for_status()
            with tmp.open('wb') as f:
                for chunk in r.iter_content(4 * 1024 * 1024): f.write(chunk)
        tmp.rename(dest)
    coast = ROOT / 'raw/ne_50m_coastline'
    if not coast.exists():
        with zipfile.ZipFile(ROOT / 'raw/ne_50m_coastline.zip') as z: z.extractall(coast)

def plain(v):
    return np.asarray(np.ma.filled(v, np.nan), dtype=np.float64)

def read_monthly(path, kind):
    with Dataset(path) as ds:
        latname, lonname = ('lat', 'lon') if 'lat' in ds.variables else ('latitude', 'longitude')
        lat, lon = plain(ds[latname][:]), plain(ds[lonname][:])
        assert ds[latname].units in ('degrees_north', 'degree_north')
        assert ds[lonname].units in ('degrees_east', 'degree_east')
        tvar = ds['time']; time = plain(tvar[:])
        if kind == 'temperature':
            assert tvar.units == 'year A.D.'
            yy = np.floor(time).astype(int)
            mm = np.rint((time-yy)*12 + 0.5).astype(int)
            expected_decimal = yy + (mm-0.5)/12
            assert np.max(np.abs(expected_decimal-time)) < 1e-7
            variables = ['temperature']
        else:
            dates = num2date(time, tvar.units, calendar=getattr(tvar, 'calendar', 'standard'))
            yy = np.array([d.year for d in dates]); mm = np.array([d.month for d in dates])
            variables = ['solar_mon', 'toa_sw_all_mon']
        idx = np.flatnonzero((yy >= 2001) & (yy <= 2025))
        keys = list(zip(yy[idx].tolist(), mm[idx].tolist()))
        expected = [(int(y), m) for y in YEARS for m in range(1,13)]
        assert keys == expected, f'{kind}: missing, duplicate or unordered months'
        assert len(idx) == 300
        arrays = []
        units = {}
        for name in variables:
            v = ds[name]
            assert set(v.dimensions) == {'time', latname, lonname}, (name, v.dimensions)
            units[name] = v.units
            assert v.units in (('degree C', 'degrees_C', 'degC', 'degree_Celsius') if kind == 'temperature' else ('W m-2','W/m^2','W m^-2'))
            # netCDF4 fancy indexing, followed by explicit dimension normalization.
            sl = [slice(None)] * 3; sl[v.dimensions.index('time')] = idx
            a = plain(v[tuple(sl)])
            a = np.transpose(a, [v.dimensions.index(n) for n in ('time',latname,lonname)])
            a[~np.isfinite(a)] = np.nan
            for attr, op in [('valid_min',np.less), ('valid_max',np.greater)]:
                if hasattr(v, attr): a[op(a, float(v.getncattr(attr)))] = np.nan
            arrays.append(a)
        attrs = {name: str(ds.getncattr(name)) for name in ds.ncattrs()}
        if kind=='asr':
            assert '4.2.1' in (str(path)+' '+json.dumps(attrs)), 'CERES edition 4.2.1 not verifiable from filename or metadata'
        period = {'first': f'{yy[0]:04d}-{mm[0]:02d}', 'last': f'{yy[-1]:04d}-{mm[-1]:02d}'}
    # Change longitude convention and permute; do not interpolate values.
    lon = (lon+180)%360-180
    ilat, ilon = np.argsort(lat), np.argsort(lon)
    lat, lon = lat[ilat], lon[ilon]
    np.testing.assert_allclose(lat, LAT, atol=1e-9, rtol=0)
    np.testing.assert_allclose(lon, LON, atol=1e-9, rtol=0)
    arrays = [a[:,ilat,:][:,:,ilon] for a in arrays]
    a = arrays[0] if kind == 'temperature' else arrays[0] - arrays[1]
    assert a.shape == (300,180,360)
    info = dict(path=str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path), sha256=sha256(path), bytes=path.stat().st_size,
                units=units, selected_months=len(idx), source_period=period, source_attributes=attrs,
                monthly_missing_values=int(np.count_nonzero(~np.isfinite(a))),
                sorted_latitude=True, sorted_longitude=True,
                regridding='none; 1-degree cell centers identical; longitude convention and index permutation only')
    return a, info

def annual_reference(a):
    days = np.array([calendar.monthrange(int(y),m)[1] for y in YEARS for m in range(1,13)],dtype=float).reshape(25,12)
    monthly = a.reshape(25,12,180,360)
    # Ordinary sum propagates NaN: incomplete years never use shortened denominators.
    annual = np.sum(monthly*days[:,:,None,None], axis=1)/days.sum(axis=1)[:,None,None]
    valid_months = np.sum(np.isfinite(monthly),axis=1).astype('uint8')
    reference = np.mean(annual,axis=0)  # 25 equally weighted complete years, otherwise NaN
    anom = annual-reference[None,:,:]
    return annual, reference, anom, valid_months, days

def five_year_means(a):
    """Five non-overlapping averages of five annual fields; propagate NaN."""
    assert a.shape==(25,180,360)
    return np.mean(a.reshape(5,5,180,360),axis=1)

def color_indices(a, maximum):
    result=np.full(a.shape,10,dtype=np.uint8)
    good=np.isfinite(a)
    neg=good & (a<0); pos=good & (a>0)
    # Saturate only the display; retain the complete numerical fields.
    display=np.clip(a,-maximum,maximum)
    result[neg]=9-np.minimum(9,np.ceil(-display[neg]/maximum*10).astype(int)-1)
    result[pos]=11+np.minimum(9,np.ceil(display[pos]/maximum*10).astype(int)-1)
    return result

def projection_checks():
    testlon,testlat=np.meshgrid(np.linspace(-179,179,73),np.linspace(-89,89,71))
    x,y=MOLL(testlon,testlat)
    theta=np.arcsin(y/SQ2)
    phi=np.arcsin(np.clip((2*theta+np.sin(2*theta))/np.pi,-1,1))
    lam=np.pi*x/(2*SQ2*np.cos(theta))
    inverse_error=max(float(np.max(np.abs(np.rad2deg(phi)-testlat))),float(np.max(np.abs(np.rad2deg(lam)-testlon))))
    assert inverse_error<1e-7
    # Numerical Jacobian of independent PROJ forward transform, in radians.
    lon,lat=np.meshgrid(np.deg2rad(np.linspace(-170,170,19)),np.deg2rad(np.linspace(-88,88,45)))
    h=1e-6
    xp,yp=MOLL(lon+h,lat,radians=True);xm,ym=MOLL(lon-h,lat,radians=True)
    xq,yq=MOLL(lon,lat+h,radians=True);xr,yr=MOLL(lon,lat-h,radians=True)
    det=((xp-xm)*(yq-yr)-(xq-xr)*(yp-ym))/(4*h*h)
    area_error=float(np.max(np.abs(det/np.cos(lat)-1)))
    assert area_error<1e-5
    x0,y0=MOLL([0,180,-180,0,0],[0,0,0,90,-90])
    np.testing.assert_allclose(x0,[0,2*SQ2,-2*SQ2,0,0],atol=1e-9)
    np.testing.assert_allclose(y0,[0,0,0,SQ2,-SQ2],atol=1e-9)
    assert abs(np.pi*(2*SQ2)*SQ2 - 4*np.pi) < 1e-12
    return dict(projection='+proj=moll +lon_0=0 +R=1',central_meridian=0,
                inverse_vs_proj_max_error_degrees=inverse_error,
                max_relative_area_jacobian_error=area_error, sphere_and_ellipse_area=4*np.pi,
                geographic_controls_pass=True)

def projected_coast():
    reader=shapefile.Reader(str(ROOT/'raw/ne_50m_coastline/ne_50m_coastline.shp'))
    lines=[]
    for shape in reader.shapes():
        points=np.array(shape.points)
        for start,end in zip(shape.parts,list(shape.parts)[1:]+[len(points)]):
            part=points[start:end]
            # Split antimeridian discontinuities rather than connecting across the map.
            for p in np.split(part,np.flatnonzero(np.abs(np.diff(part[:,0]))>180)+1):
                if len(p)<2: continue
                x,y=MOLL(p[:,0],p[:,1]); lines.append(np.column_stack([x,y]))
    return lines

def render_maps(products):
    # Inverse map pixel centers into the actual native 1-degree cell.
    # No bilinear interpolation, smoothing or artificial geographical detail.
    width,height=1800,900
    x=(np.arange(width)+0.5)/width*(4*SQ2)-2*SQ2
    y=SQ2-(np.arange(height)+0.5)/height*(2*SQ2)
    xx,yy=np.meshgrid(x,y)
    inside=(xx/(2*SQ2))**2+(yy/SQ2)**2<=1
    theta=np.arcsin(yy/SQ2)
    phi=np.arcsin(np.clip((2*theta+np.sin(2*theta))/np.pi,-1,1))
    lam=np.pi*xx/(2*SQ2*np.cos(theta))
    ilat=np.clip(np.floor(np.rad2deg(phi)+90).astype(int),0,179)
    ilon=np.clip(np.floor(np.rad2deg(lam)+180).astype(int),0,359)
    lines=projected_coast()
    fig=plt.figure(figsize=(10,5),dpi=180,facecolor='white')
    ax=fig.add_axes([0.002,0.004,0.996,0.992])
    ax.set(xlim=(-2*SQ2,2*SQ2),ylim=(-SQ2,SQ2),aspect='equal');ax.axis('off')
    im=ax.imshow(np.ones((height,width,3),dtype=np.uint8)*255,
                 extent=(-2*SQ2,2*SQ2,-SQ2,SQ2),origin='upper',interpolation='nearest',zorder=1)
    ax.add_collection(LineCollection(lines,colors='black',linewidths=0.24,zorder=2,antialiaseds=True))
    ax.add_patch(Ellipse((0,0),4*SQ2,2*SQ2,fill=False,color='black',linewidth=0.5,zorder=3))
    fields=[('reference',np.zeros((180,360)),1.)]
    for name,p in products.items():
        fields.extend((f'{name}_{year}',p['anom'][i],p['M']) for i,year in enumerate(YEARS))
        fields.extend((f'{name}_{start}-{end}',p['fiveyear'][i],p['M']) for i,(start,end) in enumerate(PERIODS))
    for label,a,maximum in fields:
        ci=color_indices(a,maximum)
        rgb=PALETTE[ci[ilat,ilon]].copy()
        missing=~np.isfinite(a[ilat,ilon]) & inside
        rgb[missing]=[210,214,220]
        rgb[~inside]=255
        im.set_data(rgb)
        fig.savefig(ROOT/'assets'/f'{label}.png',dpi=180,facecolor='white')
        print('Rendered',label,flush=True)
    plt.close(fig)

def save_netcdf(products,source_info):
    coords={'year':YEARS,'lat':LAT,'lon':LON}
    global_attrs=dict(Conventions='CF-1.10',title='Annual spatial anomalies, 2001-2025',
        reference_period='2001-2025',annual_aggregation='monthly means weighted by Gregorian days per month',
        reference_aggregation='arithmetic mean of 25 annual fields; each year has equal weight',
        missing_data_policy='annual field requires 12 valid months; reference requires 25 complete years; NaN propagated',
        temperature_product='Berkeley Earth High-Resolution global TAVG official 1-degree field; user-approved replacement for discontinued original product',
        regridding='none; index permutation only',history='Generated by reproduce.py',
        source_sha256=json.dumps({k:v['sha256'] for k,v in source_info.items()}),
        color_scale_policy='user-fixed limits; values outside limits use endpoint colors; stored values are not clipped')
    ds=xr.Dataset(coords=coords,attrs=global_attrs)
    ref=xr.Dataset(coords={'lat':LAT,'lon':LON},attrs=global_attrs)
    periods=xr.Dataset(coords={'period':[f'{start}-{end}' for start,end in PERIODS],'lat':LAT,'lon':LON},
        attrs={**global_attrs,'title':'Five-year spatial anomalies, 2001-2025',
               'period_aggregation':'arithmetic mean of five annual anomaly fields; each year has equal weight; aggregate before display clipping'})
    for name,p in products.items():
        color_attrs={'color_scale_minimum':-p['M'],'color_scale_maximum':p['M'],
                     'color_scale_saturation':'endpoint colors beyond limits; numerical data are not clipped'}
        ds[name+'_anomaly']=(('year','lat','lon'),p['anom'],{'units':p['units'],'long_name':p['title']+' anomaly from 2001-2025',**color_attrs})
        ds[name+'_annual']=(('year','lat','lon'),p['annual'],{'units':p['units'],'long_name':p['title']+' annual mean'+(' (source temperature anomalies)' if name=='temperature' else '')})
        ds[name+'_valid_months']=(('year','lat','lon'),p['valid_months'],{'long_name':'Number of finite monthly inputs in year','units':'1'})
        ref[name+'_reference']=(('lat','lon'),p['ref'],{'units':p['units'],'long_name':p['title']+' 25-year reference'+(' of source anomalies, not absolute temperature' if name=='temperature' else '')})
        ref[name+'_complete_years']=(('lat','lon'),np.sum(np.isfinite(p['annual']),axis=0).astype('uint8'),{'units':'1'})
        periods[name+'_anomaly']=(('period','lat','lon'),p['fiveyear'],{'units':p['units'],'long_name':p['title']+' five-year mean anomaly from 2001-2025',**color_attrs})
        periods[name+'_valid_years']=(('period','lat','lon'),np.isfinite(p['anom']).reshape(5,5,180,360).sum(axis=1).astype('uint8'),{'units':'1','long_name':'Number of finite annual anomalies in five-year period'})
    periods['start_year']=('period',[start for start,end in PERIODS],{'units':'1'})
    periods['end_year']=('period',[end for start,end in PERIODS],{'units':'1'})
    for out in (ds,ref,periods):
        out['lat'].attrs={'standard_name':'latitude','units':'degrees_north','axis':'Y','bounds':'lat_bnds'}
        out['lon'].attrs={'standard_name':'longitude','units':'degrees_east','axis':'X','bounds':'lon_bnds'}
        out['lat_bnds']=(('lat','bnds'),np.column_stack([LAT-.5,LAT+.5]))
        out['lon_bnds']=(('lon','bnds'),np.column_stack([LON-.5,LON+.5]))
        area=np.deg2rad(1)*(np.sin(np.deg2rad(LAT+.5))-np.sin(np.deg2rad(LAT-.5)))[:,None]*np.ones((1,360))
        out['cell_area_unit_sphere']=(('lat','lon'),area,{'units':'1','long_name':'Cell solid angle in steradians'})
    ds['year'].attrs={'long_name':'Gregorian calendar year','units':'1'}
    for out,filename in [(ds,'annual_anomalies_2001-2025.nc'),(ref,'reference_fields_2001-2025.nc'),(periods,'five_year_anomalies_2001-2025.nc')]:
        enc={n:dict(zlib=True,complevel=5,shuffle=True) for n in out.data_vars}
        out.to_netcdf(ROOT/'data'/filename,engine='netcdf4',encoding=enc)

def build_html(products,report):
    template=(ROOT/'presentation_template.html').read_text()
    cards=[]
    def number(n): return f'{n:g}'.replace('.',',')
    def legend(p):
        swatches=''.join(f'<span style="background:rgb({r},{g},{b})"></span>' for r,g,b in PALETTE)
        return f'<div class="legend"><div class="swatches">{swatches}</div><div class="ticks"><span>−{number(p["M"])} {p["display_units"]}</span><span>0</span><span>+{number(p["M"])} {p["display_units"]}</span></div></div>'
    partial='asr' not in products
    entries=[(str(y),str(y),'annual') for y in YEARS]+[(f'{start}-{end}',f'{start}–{end}','fiveyear') for start,end in PERIODS]+[('reference','Referenční období 2001–2025','reference')]
    for year,label,kind in entries:
        reference=kind=='reference'
        figures=[]
        for name in ['asr','temperature']:
            if name not in products:
                figures.append('<figure><figcaption><span>Anomálie ASR</span><small>W/m²</small></figcaption><div class="unavailable"><strong>Čeká na skutečná data CERES</strong><span>Archiv NASA vyžaduje přihlášení Earthdata.<br>Žádné hodnoty ani barevná škála ASR nebyly odhadnuty.</span></div></figure>')
                continue
            p=products[name]
            image='reference' if reference else f'{name}_{year}'
            figures.append(f'<figure><figcaption><span>{p["display_title"]}</span><small>{p["display_units"]}</small></figcaption><img width="1800" height="900" src="assets/{image}.png" alt="{p["display_title"]}, {label}, Mollweideovo zobrazení" loading="lazy">{legend(p)}</figure>')
        subtitle='Definice reference · Δ = 0' if reference else 'Průměr 5 ročních anomálií · reference 2001–2025' if kind=='fiveyear' else 'Roční průměr · odchylka od 2001–2025'
        cards.append(f'<section class="year-card" data-year="{year}" data-kind="{kind}" id="year-{year}"><div class="year-heading"><h2>{label}</h2><span>{subtitle}</span></div><div class="pair">'+''.join(figures)+'</div></section>')
    replacements={
        '{{CARDS}}':''.join(cards),
        '{{YEAR_OPTIONS}}':''.join(f'<option value="{y}">{y}</option>' for y in YEARS),
        '{{PERIOD_OPTIONS}}':''.join(f'<option value="{start}-{end}">{start}–{end}</option>' for start,end in PERIODS),
        '{{ASR_MAX}}':number(products['asr']['M']) if not partial else 'neurčeno', '{{T_MAX}}':number(products['temperature']['M']),
        '{{ASR_EXTREME}}':number(round(products['asr']['extreme'],6)) if not partial else 'nezjištěna',
        '{{T_EXTREME}}':number(round(products['temperature']['extreme'],6)),
        '{{ASR_MISSING}}':str(report['fields']['asr']['incomplete_reference_cells']) if not partial else 'neověřeno',
        '{{T_MISSING}}':str(report['fields']['temperature']['incomplete_reference_cells']),
    }
    for k,v in replacements.items(): template=template.replace(k,v)
    if partial:
        template=template.replace('AUTOMATICKÉ KONTROLY: PROŠLY','TEPLOTA OVĚŘENA · ASR ČEKÁ NA DATA')
        template=template.replace('<main class="wrap">','<main class="wrap"><div class="partial-banner"><strong>Rozpracovaný atlas — chybí vstup CERES.</strong> Teplotní mapy jsou vypočítány ze skutečných dat. Dvojice map a společný protokol ještě nejsou kompletní. Pro pokračování je nutné přihlášení do NASA Earthdata nebo lokální původní NetCDF CERES EBAF Ed4.2.1.</div>')
        template=template.replace('ASR ±neurčeno W/m²','ASR čeká na data')
        template=template.replace('Oba vstupy mají všech 300 jedinečných po sobě jdoucích měsíců.','Teplotní vstup má všech 300 jedinečných po sobě jdoucích měsíců. CERES nebyl zpřístupněn, jeho časovou úplnost ani prostorová pole nelze ověřit.')
        template=template.replace('Oba produkty již mají totožné středy 1° buněk.','Teplotní produkt má ověřené středy 1° buněk. Pro CERES je shoda zatím pouze očekávána podle dokumentace; bude ověřena po dodání NetCDF.')
        template=template.replace('Největší skutečná absolutní anomálie je nezjištěna W/m² u ASR a','Největší absolutní anomálie ASR zatím není známa; teplotní maximum je')
        template=template.replace('Nahoru zaokrouhlená maxima škál jsou neurčeno W/m² a','Škála ASR ještě není určena; teplotní škála je ±')
        template=template.replace('Ověřeny byly časové osy, jednotky, společné souřadnice,','U teploty byly ověřeny časová osa, jednotky, souřadnice,')
        template=template.replace('Původní NetCDF z oficiálního ASDC.','Oficiální ASDC vyžaduje přihlášení; data zatím nebyla stažena.')
        template=template.replace('25 ročních dvojic map','25 teplotních map · ASR čeká na data')
        template=template.replace('50 map · chronologické pořadí','25 teplotních map · ASR čeká na data')
        template=template.replace('href="data/reference_fields_2001-2025.nc"','href="data/temperature_reference_2001-2025.nc"')
        template=template.replace('href="data/annual_anomalies_2001-2025.nc"','href="data/temperature_annual_anomalies_2001-2025.nc"')
        template=template.replace('Referenční pole · NetCDF','Teplotní reference · NetCDF').replace('Roční anomálie · NetCDF','Teplotní roční anomálie · NetCDF')
        template=template.replace('</style>','.unavailable{aspect-ratio:2;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;border:1px dashed #ccd5d9;border-radius:50%;color:#70808a;gap:12px;margin-top:3px}.unavailable strong{font-size:13px;font-weight:500}.unavailable span{font-size:11px;line-height:1.7}.partial-banner{background:#fff6e7;border:1px solid #e5d3ad;border-radius:6px;color:#705b36;padding:14px 20px;margin-top:23px;font-size:12px}.partial-banner strong{display:block;font-size:13px;margin-bottom:4px}</style>')
    (ROOT/'index.html').write_text(template)

def build_readme(products,report,source_info):
    partial='asr' not in products
    stats=[]
    for name,p in products.items():
        f=report['fields'][name]
        stats.append(f'| {p["display_title"]} | {p["extreme"]:.12g} | ±{p["M"]:g} {p["display_units"]} | {f["complete_reference_cells"]:,} | {f["mean_of_anomalies_max_abs"]:.3e} |')
    source_lines=[]
    for name,info in source_info.items():
        source_lines.append(f'- `{info["path"]}` — SHA-256 `{info["sha256"]}`.')
    text=f'''# Globální atlas anomálií 2001–2025

{'**Stav: ROZPRACOVÁNO. Teplotní část je dokončena; CERES vyžaduje přihlášení NASA Earthdata. ASR nebylo vypočítáno a jeho škála není určena.**' if partial else '**Stav: dokončeno. Oba prostorové vstupy obsahují všech 300 požadovaných měsíců. Automatické numerické kontroly prošly.**'}

## Otevření a obsah

Otevřete `index.html` přímo v běžném prohlížeči. Zachovejte relativní strukturu složek. Prezentace nepotřebuje server, internet ani CDN. Nahoře lze přepnout mezi 25 ročními a pěti pětiletými dvojicemi, vybrat rok/období, přejít na předchozí/další položku, zobrazit chronologický přehled vybrané skupiny nebo referenční pohled. Fungují také šipky klávesnice. Bez JavaScriptu jsou dostupné všechny mapy pod sebou.

- `assets/`: 1800 × 900 px mapy PNG; všechny mají totožný rozsah a projekci.
- `data/`: {'temperature_reference_2001-2025.nc a temperature_annual_anomalies_2001-2025.nc; zatím pouze teplota' if partial else 'reference_fields_2001-2025.nc a annual_anomalies_2001-2025.nc'}.
- `data/five_year_anomalies_2001-2025.nc`: pětileté anomálie pro 2001–2005, 2006–2010, 2011–2015, 2016–2020 a 2021–2025, v původních číselných hodnotách bez oříznutí.
- `reproduce.py`, `requirements.txt`, `presentation_template.html`: kompletní reprodukční zdroje.
- `validation.json`: numerické kontroly a skutečné extrémy včetně roku a souřadnic.
- `provenance.json`: zdrojové atributy, soubory, časový rozsah, jednotky, URL a SHA-256.
- `raw/`: neměněné stažené vstupy; `docs/`: oficiální dokumentace a náhledy.

## Původ a verze dat

**CERES:** NASA CERES Energy Balanced and Filled (EBAF) TOA Monthly Means, Edition4.2.1, regionální pole 1° × 1°. [Oficiální produkt](https://doi.org/10.5067/TERRA-AQUA-NOAA20/CERES/EBAF-TOA_L3B004.2.1), [archiv NASA ASDC](https://search.earthdata.nasa.gov/search/granules?p=C3880497643-LARC_CLOUD). Požadované proměnné jsou `solar_mon` (příchozí sluneční tok) a `toa_sw_all_mon` (odražený krátkovlnný tok při všech podmínkách oblačnosti), v W m⁻². ASR = `solar_mon - toa_sw_all_mon`; nejde o celkový čistý radiační tok, který obsahuje i dlouhovlnné záření. Použita je dokumentace Data Quality Summary V8 z 10. 9. 2026, uložená lokálně v `docs/ceres_DQS.pdf`.

**Berkeley Earth:** High-Resolution Global Monthly Average Temperature (TAVG), oficiálně poskytovaná agregovaná varianta **1° × 1°**, soubor `Global_TAVG_Gridded_1deg.nc`; vytvořen 29. 10. 2026 11:03:07. Vstup pokrývá 1850-01 až 2026-09. Analýza vybírá jen 2001-01 až 2025-12. Tento předběžný produkt byl **výslovně schválen zadavatelem jako náhrada původního Land and Ocean**, jehož aktualizace skončily v roce 2025. Nejde o smíšení staré a nové generace: celé období používá stejný nový produkt. [Oficiální přehled a stažení](https://berkeleyearth.org/data/), [přímý NetCDF](https://storage.googleapis.com/berkeley-earth-temperature-hr/global/gridded/Global_TAVG_Gridded_1deg.nc).

**Mořský led:** podle [oficiálního popisu metody Berkeley Earth](https://berkeleyearth.org/august-2026-temperature-update/) se nad ledem extrapolují teplotní anomálie vzduchu z pevniny. Nad otevřeným oceánem se používá teplota povrchu moře. Vstup je kombinovaná povrchová teplota, nikoli homogenní měření teploty vzduchu ve výšce 2 m po celé Zemi. Původní měsíční teplotní klimatologii není nutné rekonstruovat; přepočítáváme referenci vstupních teplotních anomálií podle zadání.

**Pobřeží:** Natural Earth `ne_50m_coastline`, **4.1.0 podle VERSION.txt ve staženém ZIP**, měřítko 1 : 50 milionům; bez státních hranic. [Oficiální zdroj](https://www.naturalearthdata.com/downloads/50m-physical-vectors/50m-coastline/). Projekce používá [PROJ Mollweide](https://proj.org/en/stable/operations/projections/moll.html).

## Metoda

### ASR a planetární albedo

ASR (Absorbed Solar Radiation) je sluneční tok pohlcený soustavou Země–atmosféra, určený na TOA jako příchozí sluneční tok minus odražený krátkovlnný tok, v W/m². Pro stejnou oblast a stejné průměrované období definujeme albedo α = F_odr / F_in při F_in > 0. Potom přesně platí **ASR = F_in − F_odr = F_in (1 − α)**. Při stejném F_in je **ΔASR = −F_in Δα**: růst ASR odpovídá poklesu planetárního albeda a naopak. Jestliže se mění i příchozí tok, zahrnuje změna ASR oba příspěvky; samotná anomálie ASR neurčuje jednoznačně změnu albeda. Albedo zde popisuje odrazivost soustavy Země–atmosféra včetně atmosféry, oblaků a povrchu. Jde o definici fyzikálních veličin; mapám nejsou přisuzovány příčiny změn. Definice a energetické rozdělení: [NASA radiation budget](https://science.nasa.gov/ems/13_radiationbudget/) a [NASA clouds and radiation](https://science.nasa.gov/earth/earth-observatory/clouds-and-radiation/).

1. Načtení skutečných prostorových NetCDF proměnných, maskování `_FillValue`, `missing_value`, neplatných rozsahů a nekonečen; výpočet ve float64.
2. Ověření přesně 300 jedinečných měsíců v pořadí 2001-01…2025-12. Čas CERES se dekóduje podle jednotek CF. Desetinné roky Berkeley Earth se dekódují podle středů měsíců a kontrolují zpětným přepočtem.
3. Síť: šířky −89,5…+89,5°, délky −179,5…+179,5°, kroky 1°. CERES 0…360° se převádí modulo 360° a sloupce se přeuspořádají. Žádná prostorová interpolace ani převzorkování nejsou potřeba; shoda středů se numericky kontroluje. {'Shoda s CERES ještě čeká na vstup.' if partial else 'Obě sítě byly ověřeny jako totožné.'}
4. Pro každou buňku a rok: `annual = sum(monthly * calendar_days) / sum(calendar_days)`. Použije se gregoriánský kalendář včetně 29. února.
5. Roční buňka se počítá pouze při 12 platných měsících. Reference je běžný aritmetický průměr všech 25 úplných ročních hodnot, každý rok má váhu 1/25. Pokud jediný rok chybí, reference i všechny anomálie této buňky zůstávají NaN. Neprůměruje se z kratšího počtu roků.
6. `anomaly[year,lat,lon] = annual[year,lat,lon] - reference[lat,lon]`. V NetCDF jsou vedle anomálií i roční vstupní průměry a počty platných měsíců. Teplotní reference je referencí **vstupních anomálií**, ne absolutní teplotou.
7. Pro každou buňku je pětiletá anomálie aritmetickým průměrem pěti ročních anomálií, každý rok s vahou 1/5. Pětiletí jsou nepřekrývající se bloky 2001–2005, 2006–2010, 2011–2015, 2016–2020 a 2021–2025. Reference zůstává 2001–2025. Průměrují se původní hodnoty před přiřazením barev. Každá buňka vyžaduje všech pět platných ročních anomálií.
8. Barevné meze jsou **podle aktualizovaného zadání pevně ±20 W/m² pro ASR a ±4 °C pro teplotu**, shodně pro roční a pětileté mapy. Skutečné maximum se nadále vypočítá a uloží, neurčuje však tyto meze. Hodnoty pod −M mají stejnou modrou jako −M a hodnoty nad +M stejnou červenou jako +M. Oříznutí se používá pouze při přiřazení barev; NetCDF obsahuje neoříznuté hodnoty.
9. Deset záporných a deset kladných stejně širokých intervalů, bílá pouze přesná nula. Po oříznutí zobrazení jsou záporné intervaly `[−M,−0.9M), …, [−0.1M,0)`, kladné `(0,0.1M], …, (0.9M,M]`. Středový bílý proužek v legendě pouze označuje nulový bod; nemá nenulovou číselnou šířku. NaN je šedá `#d2d6dc` a není součástí číselné škály.

## Matematické zobrazení

Sférické plochojevné Mollweideovo zobrazení, centrální poledník 0°, jednotková koule (`+proj=moll +lon_0=0 +R=1`). Pro zeměpisnou délku λ, šířku φ a pomocný úhel θ platí:

```text
2θ + sin(2θ) = π sin(φ)
x = (2√2/π) λ cos(θ)
y = √2 sin(θ)
```

Elipsa má poloosy 2√2 a √2, tedy obsah 4π shodný s povrchem jednotkové koule. Renderer používá **přesnou inverzi pro středy obrazových bodů**: z x,y získá λ,φ a převezme hodnotu obsahující původní 1° buňky. Nevytváří jemnější geografická data ani interpolované hodnoty. Hranice barevných buněk mají běžnou konečnou přesnost rasteru. Pobřeží se samostatně projektuje pomocí PROJ; přechody přes datovou hranici se rozpojují. Pozadí a nulové referenční mapy jsou bílé.

Numerické srovnání inverze s nezávislou dopřednou projekcí PROJ: maximální chyba **{report['projection']['inverse_vs_proj_max_error_degrees']:.3e}°**. Numerický Jakobián byl testován v 855 bodech od −88° do +88° a ověřen proti `cos(φ)`, maximální relativní chyba **{report['projection']['max_relative_area_jacobian_error']:.3e}**. Kontrolní body zahrnují oba póly a oba konce datové hranice. Obě mapy používají stejný obrazový rastr i geografický rozsah.

## Výsledky kontrol a škály

| Veličina | Skutečné max. absolutní anomálie | Pevná škála | Úplné referenční buňky | Max. absolutní průměr 25 anomálií |
|---|---:|---:|---:|---:|
{chr(10).join(stats)}

Teplotní vstup obsahuje všech 300 měsíců, ale má **21 539 chybějících měsíčních hodnot**. Striktní úplná reference chybí v **826 z 64 800 buněk**, takže pro všechny roční mapy má teplota stejnou masku. Změny masky tak nevytvářejí falešné rozdíly mezi roky. Všechny neúplné buňky zůstávají NaN; nedoplňují se globálním průměrem ani nulou. Pro každý roční prostorový rastr je ověřena nenulová prostorová směrodatná odchylka. Referenční bílý pohled je definice nulové odchylky reference vůči sobě; u chybějících vstupů neznamená existenci numerické reference.

Podrobnosti a souřadnice extrémů jsou v `validation.json`, včetně počtů hodnot mimo barevné meze pro roční i pětileté mapy. V každé úplné buňce je ověřen numericky nulový průměr 25 ročních i pěti pětiletých anomálií. Správnost pětiletých anomálií se nezávisle kontroluje proti rozdílu průměru pěti ročních polí a společné reference. {'Kontroly CERES nebyly provedeny; celkový stav je PARTIAL.' if partial else 'Kontroly obou vstupů prošly; celkový stav je PASS.'}

## Reprodukce

Python 3.12 nebo novější:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python reproduce.py
```

Příkazy spouštějte ve složce atlasu. Výpočty i mapy se znovu vytvoří z neměněných souborů v `raw/`. Pokud již máte původní prostorový soubor CERES Ed4.2.1 pod jiným názvem:

```sh
.venv/bin/python reproduce.py --ceres-file /absolutni/cesta/k/CERES_EBAF_Ed4.2.1.nc
```

Volba `--download` doplní chybějící vstupy z uvedených oficiálních URL. NASA vyžaduje platnou relaci/přihlášení Earthdata; soubor lze stáhnout v prohlížeči z oficiálního archivu a beze změn uložit do `raw/`. Skript nepřistupuje k heslům prohlížeče. Aktualizované soubory na proměnlivých URL mohou mít jiný obsah; přesná reprodukce této dodávky používá přiložené původní soubory a SHA-256 v `provenance.json`.

`--skip-maps` je určeno jen pro změny HTML při nezměněných datech a již existujících mapách. `--temperature-only` vytvoří výslovně označený rozpracovaný náhled bez ASR; **není to kompletní splnění zadání**.

## Kontrolní součty a citace

{chr(10).join(source_lines)}

CERES: Loeb et al. (2018), DOI [10.1175/JCLI-D-17-0208.1](https://doi.org/10.1175/JCLI-D-17-0208.1); Loeb et al. (2024), DOI [10.1175/JCLI-D-24-0180.1](https://doi.org/10.1175/JCLI-D-24-0180.1). Data jsou z NASA Langley Research Center CERES / Atmospheric Science Data Center. Teplotní data: Berkeley Earth, [www.berkeleyearth.org](https://berkeleyearth.org/); současná datová stránka uvádí licenci CC BY-NC 4.0. Natural Earth: public domain.

ASR je tok na TOA (W/m²), teplota je povrchová veličina (°C). Mapy jsou určeny k časovému a geografickému porovnávání. Jejich anomálie se přímo energeticky nezaměňují a samotné mapy nedokazují kauzalitu. Žádné příčiny změn nejsou interpretovány.
'''
    (ROOT/'METHODOLOGY.md').write_text(text)
    brief=f'''# Globální atlas anomálií 2001–2025

{'**Rozpracováno:** teplotní mapy jsou hotové; ASR čeká na přístup k původnímu CERES NetCDF.' if partial else '**Dokončeno:** 25 ročních a 5 pětiletých dvojic map ASR a teploty, společná síť 1° × 1°, Mollweideovo plochojevné zobrazení s centrálním poledníkem 0°.'}

Otevřete **index.html** přímo v prohlížeči. Soubory v `assets/` ponechte vedle HTML. Dokument funguje offline, bez serveru a CDN. Ovládání přepíná mezi ročními a pětiletými mapami a nabízí výběr roku/období, předchozí/další položku, přehled celé skupiny a bílý referenční pohled.

## Vstupy

- **NASA CERES EBAF-TOA Edition4.2.1**, skutečné měsíční regionální NetCDF proměnné `solar_mon` a `toa_sw_all_mon`, W m⁻². ASR = příchozí sluneční tok minus odražený krátkovlnný tok. [Oficiální archiv](https://search.earthdata.nasa.gov/search/granules?p=C3880497643-LARC_CLOUD).
- **Berkeley Earth High-Resolution global TAVG, oficiální 1° varianta**, soubor vytvořený 29. 10. 2026. Tato předběžná generace byla výslovně schválena jako náhrada ukončeného původního produktu. Celé období používá stejnou generaci. [Oficiální zdroj](https://berkeleyearth.org/data/). Nad mořským ledem se extrapolují anomálie teploty vzduchu z pevniny; nad otevřeným oceánem jde o teplotu povrchu moře.
- **Natural Earth 50m coastline, 4.1.0** podle staženého VERSION.txt; bez hranic států.

## Výpočet a škály

ASR je pohlcený sluneční tok soustavy Země–atmosféra. Platí **ASR = F_in (1 − α)**, kde α je planetární albedo definované jako podíl odraženého a příchozího krátkovlnného toku pro stejnou oblast a období (při F_in > 0). **Při stejném F_in odpovídá růst ASR poklesu albeda a naopak.** Při změně příchozího toku nelze samotnou anomálii ASR jednoznačně převést na změnu albeda. Podrobná definice se zdroji je v úvodu HTML a v `METHODOLOGY.md`.

V každé buňce se měsíce váží počtem dní v gregoriánském kalendáři. Reference je průměr 25 ročních průměrů se stejnou vahou roků. Anomálie = roční průměr minus místní reference. Roční hodnota vyžaduje 12 platných měsíců a reference 25 úplných let. Neúplné buňky zůstávají NaN a v mapě jsou šedé.

Pětileté mapy pokrývají **2001–2005, 2006–2010, 2011–2015, 2016–2020 a 2021–2025**. Každá je průměrem pěti ročních anomálií se stejnou vahou roků vůči společné referenci 2001–2025; průměrují se plné číselné hodnoty před přiřazením barev.

{'Teplotní vstup má ověřeno všech 300 měsíců; CERES zatím chybí.' if partial else 'Oba vstupy mají ověřeno všech 300 měsíců. Souřadnice jejich 1° sítí jsou totožné; u CERES se pouze přeuspořádají délky z 0…360° na −180…180°. Žádná interpolace ani převzorkování se neprovádějí.'} Teplotní úplná reference existuje v 63 974 z 64 800 buněk; 826 buněk zůstává ve všech letechch šedých.

| Veličina | Skutečné max. absolutní anomálie | Pevná škála | Úplné buňky | Max. reziduum průměru anomálií |
|---|---:|---:|---:|---:|
{chr(10).join(stats)}

Škály jsou podle zadání **±20 W/m² (ASR) a ±4 °C (teplota)**, shodně pro roční i pětileté mapy. Hodnoty mimo meze mají stejnou krajní barvu jako příslušná mez; číselná data v NetCDF nejsou oříznuta. Každá škála má deset modrých a deset červených intervalů, přesná nula je bílá. Obrazové body se matematicky promítají do skutečných 1° buněk bez vyhlazování. Kontrola proti PROJ i numerická kontrola plochojevnosti prošly.

## Soubory a reprodukce

- `data/`: {'zatím teplotní referenční pole a 25 ročních anomálií' if partial else 'referenční pole, 25 ročních anomálií, roční průměry a počty platných měsíců'} v NetCDF.
- `data/five_year_anomalies_2001-2025.nc`: pětileté anomálie a počty platných roků.
- `raw/`: neměněné stažené vstupy. `provenance.json`: jejich atributy, URL a SHA-256.
- `validation.json`: automatické kontroly, maxima a souřadnice extrémů. Celkový stav **{report['status']}**.
- `METHODOLOGY.md`: úplné technické podrobnosti, rovnice projekce, citace a zacházení s chybějícími daty.

Ve složce atlasu, s Pythonem 3.12+:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python reproduce.py
```

Jiný původní NetCDF CERES Ed4.2.1 lze zadat přes `--ceres-file /absolutni/cesta/soubor.nc`. Volba `--download` doplní chybějící vstupy; NASA vyžaduje přihlášení Earthdata. Přesná reprodukce používá přiložené původní soubory, protože živé datové URL se aktualizují. `--temperature-only` je výslovně nekompletní náhled.

ASR je tok na TOA v W/m², teplota je povrchová veličina v °C. Anomálie se přímo energeticky nezaměňují; samotné mapy nedokazují kauzalitu. Příčiny změn nejsou interpretovány.
'''
    (ROOT/'README.md').write_text(brief.replace('letechch','letech'))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--download',action='store_true');parser.add_argument('--skip-maps',action='store_true');parser.add_argument('--ceres-file',type=Path,help='Alternative original CERES Ed4.2.1 spatial NetCDF');parser.add_argument('--temperature-only',action='store_true',help='Explicitly incomplete preview while awaiting NASA access');args=parser.parse_args()
    for name in ['raw','assets','data','docs']: (ROOT/name).mkdir(exist_ok=True)
    if args.download: download_inputs(include_ceres=not args.temperature_only)
    products={};source_info={};report={'status':'PARTIAL' if args.temperature_only else 'PASS','period':'2001-01/2025-12','grid_shape':[180,360],
        'five_year_periods':[[start,end] for start,end in PERIODS],
        'five_year_aggregation':'mean of five unmodified annual anomaly fields; equal year weights; NaN propagated; color saturation applied after averaging',
        'grid_identical':None if args.temperature_only else True,'fields':{},'projection':projection_checks()}
    for name,filename,kind,units,title in [('asr',CERES,'asr','W m-2','Absorbed solar radiation at TOA'),('temperature',BERKELEY,'temperature','degree_Celsius','Berkeley Earth surface temperature')]:
        if name=='asr' and args.temperature_only: continue
        source_path=args.ceres_file.resolve() if name=='asr' and args.ceres_file else ROOT/'raw'/filename
        a,info=read_monthly(source_path,kind);source_info[name]=info
        annual,ref,anom,valid,days=annual_reference(a)
        extreme=float(np.nanmax(np.abs(anom)))
        maximum=COLOR_LIMITS[name]
        fiveyear=five_year_means(anom)
        complete=np.isfinite(ref)
        residual=float(np.max(np.abs(np.mean(anom[:,complete],axis=0))))
        assert residual<1e-10
        indices=color_indices(anom,maximum)
        assert np.all(indices[anom<=-maximum]==0)
        assert np.all(indices[anom>=maximum]==20)
        period_residual=float(np.max(np.abs(np.mean(fiveyear[:,complete],axis=0))))
        assert period_residual<1e-10
        independent_period_error=0.
        for pi in range(5):
            expected=np.mean(annual[pi*5:pi*5+5],axis=0)-ref
            independent_period_error=max(independent_period_error,float(np.nanmax(np.abs(fiveyear[pi]-expected))))
        assert independent_period_error<1e-10
        assert np.all(np.isfinite(fiveyear[:,complete]))
        assert np.all(~np.isfinite(fiveyear[:,~complete]))
        spatial_stds=np.nanstd(anom,axis=(1,2));assert np.all(spatial_stds>0.01)
        assert np.all(np.isfinite(anom[:,complete]))
        assert np.all(~np.isfinite(anom[:,~complete]))
        # Independent direct weighted arithmetic at three cells, including leap years.
        finite=np.argwhere(complete);samples=finite[[0,len(finite)//2,-1]]
        sample_error=0.
        for j,k in samples:
            for yi in [0,11,14,23,24]:
                direct=math.fsum(float(a[yi*12+m,j,k])*calendar.monthrange(int(YEARS[yi]),m+1)[1] for m in range(12))/sum(calendar.monthrange(int(YEARS[yi]),m)[1] for m in range(1,13))
                sample_error=max(sample_error,abs(direct-annual[yi,j,k]))
        assert sample_error<1e-10
        products[name]=dict(annual=annual,ref=ref,anom=anom,fiveyear=fiveyear,valid_months=valid,extreme=extreme,M=maximum,units=units,title=title,
            display_units='W/m²' if name=='asr' else '°C',display_title='Anomálie ASR' if name=='asr' else 'Anomálie povrchové teploty')
        exidx=np.unravel_index(np.nanargmax(np.abs(anom)),anom.shape)
        report['fields'][name]=dict(selected_months=info['selected_months'],monthly_missing_values=info['monthly_missing_values'],
            complete_reference_cells=int(complete.sum()),incomplete_reference_cells=int((~complete).sum()),
            incomplete_annual_cells=int(np.count_nonzero(valid<12)),mean_of_anomalies_max_abs=residual,
            fixed_scale=maximum,actual_max_abs=extreme,extreme_year=int(YEARS[exidx[0]]),
            extreme_lat=float(LAT[exidx[1]]),extreme_lon=float(LON[exidx[2]]),extreme_signed_value=float(anom[exidx]),
            minimum_spatial_std=float(spatial_stds.min()),independent_weighting_check_error=sample_error,
            scale_policy='user-fixed display limit; saturation beyond endpoints; numerical values not clipped',
            annual_saturated_below=int(np.count_nonzero(anom<-maximum)),annual_saturated_above=int(np.count_nonzero(anom>maximum)),
            five_year_actual_max_abs=float(np.nanmax(np.abs(fiveyear))),
            five_year_saturated_below=int(np.count_nonzero(fiveyear<-maximum)),five_year_saturated_above=int(np.count_nonzero(fiveyear>maximum)),
            mean_of_five_year_anomalies_max_abs=period_residual,
            independent_five_year_aggregation_check_error=independent_period_error,
            saturation_checks_pass=True,
            calendar_days_per_year=days.sum(axis=1).astype(int).tolist())
        print(name,json.dumps(report['fields'][name]),flush=True)
    report['palette']={'negative_shades':10,'positive_shades':10,'exact_zero':'#ffffff','missing':'#d2d6dc',
        'bin_rule':'display clipped to [-M,M]; negative: [-M,-0.9M), ..., [-0.1M,0); positive: (0,0.1M], ..., (0.9M,M]; zero only is white; numerical values not clipped',
        'rgb':PALETTE.tolist()}
    # Boundary tests confirm that no tiny nonzero anomaly is assigned white.
    np.testing.assert_array_equal(color_indices(np.array([-100.,-1.,-.1,-1e-15,0,1e-15,.1,1.,100.]),1),[0,0,9,9,10,11,11,20,20])
    save_netcdf(products,source_info)
    if args.temperature_only:
        (ROOT/'data/annual_anomalies_2001-2025.nc').replace(ROOT/'data/temperature_annual_anomalies_2001-2025.nc')
        (ROOT/'data/reference_fields_2001-2025.nc').replace(ROOT/'data/temperature_reference_2001-2025.nc')
    if not args.skip_maps: render_maps(products)
    build_html(products,report)
    (ROOT/'validation.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    for n,p in URLS.items():
        if (ROOT/'raw'/n).exists():
            if n not in [CERES,BERKELEY]: source_info['coastline']={'path':'raw/'+n,'sha256':sha256(ROOT/'raw'/n),'version':'4.1.0'}
    for key,filename in [('asr',CERES),('temperature',BERKELEY),('coastline','ne_50m_coastline.zip')]:
        if key in source_info: source_info[key]['url']=URLS[filename]
    (ROOT/'provenance.json').write_text(json.dumps(source_info,indent=2,ensure_ascii=False)+'\n')
    build_readme(products,report,source_info)
    print('Temperature checks PASS; CERES missing.' if args.temperature_only else 'All checks PASS.', 'Atlas:',ROOT/'index.html',flush=True)

if __name__=='__main__': main()
