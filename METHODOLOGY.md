# Globální atlas anomálií 2001–2025

**Stav: dokončeno. Oba prostorové vstupy obsahují všech 300 požadovaných měsíců. Automatické numerické kontroly prošly.**

## Otevření a obsah

Otevřete `index.html` přímo v běžném prohlížeči. Zachovejte relativní strukturu složek. Prezentace nepotřebuje server, internet ani CDN. Nahoře lze přepnout mezi 25 ročními a pěti pětiletými dvojicemi, vybrat rok/období, přejít na předchozí/další položku, zobrazit chronologický přehled vybrané skupiny nebo referenční pohled. Fungují také šipky klávesnice. Bez JavaScriptu jsou dostupné všechny mapy pod sebou.

- `assets/`: 1800 × 900 px mapy PNG; všechny mají totožný rozsah a projekci.
- `data/`: reference_fields_2001-2025.nc a annual_anomalies_2001-2025.nc.
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
3. Síť: šířky −89,5…+89,5°, délky −179,5…+179,5°, kroky 1°. CERES 0…360° se převádí modulo 360° a sloupce se přeuspořádají. Žádná prostorová interpolace ani převzorkování nejsou potřeba; shoda středů se numericky kontroluje. Obě sítě byly ověřeny jako totožné.
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

Numerické srovnání inverze s nezávislou dopřednou projekcí PROJ: maximální chyba **2.217e-12°**. Numerický Jakobián byl testován v 855 bodech od −88° do +88° a ověřen proti `cos(φ)`, maximální relativní chyba **1.842e-09**. Kontrolní body zahrnují oba póly a oba konce datové hranice. Obě mapy používají stejný obrazový rastr i geografický rozsah.

## Výsledky kontrol a škály

| Veličina | Skutečné max. absolutní anomálie | Pevná škála | Úplné referenční buňky | Max. absolutní průměr 25 anomálií |
|---|---:|---:|---:|---:|
| Anomálie ASR | 38.4813166331 | ±20 W/m² | 64,800 | 1.228e-13 |
| Anomálie povrchové teploty | 6.97164536577 | ±4 °C | 63,974 | 1.350e-15 |

Teplotní vstup obsahuje všech 300 měsíců, ale má **21 539 chybějících měsíčních hodnot**. Striktní úplná reference chybí v **826 z 64 800 buněk**, takže pro všechny roční mapy má teplota stejnou masku. Změny masky tak nevytvářejí falešné rozdíly mezi roky. Všechny neúplné buňky zůstávají NaN; nedoplňují se globálním průměrem ani nulou. Pro každý roční prostorový rastr je ověřena nenulová prostorová směrodatná odchylka. Referenční bílý pohled je definice nulové odchylky reference vůči sobě; u chybějících vstupů neznamená existenci numerické reference.

Podrobnosti a souřadnice extrémů jsou v `validation.json`, včetně počtů hodnot mimo barevné meze pro roční i pětileté mapy. V každé úplné buňce je ověřen numericky nulový průměr 25 ročních i pěti pětiletých anomálií. Správnost pětiletých anomálií se nezávisle kontroluje proti rozdílu průměru pěti ročních polí a společné reference. Kontroly obou vstupů prošly; celkový stav je PASS.

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

- `raw/CERES_EBAF-TOA_Edition4.2.1_200003-202608.nc` — SHA-256 `5258da55e1df6e4ee461b708a797a1d94eb893765df3ce89ab38ab681fc31a4f`.
- `raw/Global_TAVG_Gridded_1deg.nc` — SHA-256 `937c4b1911849eb3c39cf91c4f0773f9565d412784080c4a66408b1c1eeb8d73`.
- `raw/ne_50m_coastline.zip` — SHA-256 `640f805509b822f57f4840a2e18d9ff2412cf1cf6976124701c2789436166fde`.

CERES: Loeb et al. (2018), DOI [10.1175/JCLI-D-17-0208.1](https://doi.org/10.1175/JCLI-D-17-0208.1); Loeb et al. (2024), DOI [10.1175/JCLI-D-24-0180.1](https://doi.org/10.1175/JCLI-D-24-0180.1). Data jsou z NASA Langley Research Center CERES / Atmospheric Science Data Center. Teplotní data: Berkeley Earth, [www.berkeleyearth.org](https://berkeleyearth.org/); současná datová stránka uvádí licenci CC BY-NC 4.0. Natural Earth: public domain.

ASR je tok na TOA (W/m²), teplota je povrchová veličina (°C). Mapy jsou určeny k časovému a geografickému porovnávání. Jejich anomálie se přímo energeticky nezaměňují a samotné mapy nedokazují kauzalitu. Žádné příčiny změn nejsou interpretovány.
