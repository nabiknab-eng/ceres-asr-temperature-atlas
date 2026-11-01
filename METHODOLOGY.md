# Metodika rozšíření

## Zachovaná reference a vstupy

Reference v každé buňce je **přesně převzata** z `original/data/reference_fields_2001-2025.nc`: aritmetický průměr 25 ročních průměrů 2001–2025, každý rok stejnou vahou, měsíce uvnitř roku vážené gregoriánskými dny. Nedochází k nahrazení průměrem všech 300 měsíců ani k nové referenci pro jednotlivá okna. Původní roční a pětileté NetCDF i původní HTML jsou zachovány.

CERES EBAF-TOA Edition4.2.1: `solar_mon − toa_sw_all_mon`, W/m². Celý uložený zdroj má 318 měsíců od března 2000 do srpna 2026. [Oficiální aktuální archiv](https://cmr.earthdata.nasa.gov/virtual-directory/collections/C3880497643-LARC_CLOUD), ověřeno 1. 11. 2026, uvádí tentýž soubor `CERES_EBAF-TOA_Edition4.2.1_200003-202608.nc`.

Berkeley Earth: dříve schválený High-Resolution global TAVG, oficiálně agregovaná 1° varianta `Global_TAVG_Gridded_1deg.nc`, soubor vytvořený 29. 10. 2026, pokrytí 1850-01 až 2026-09. Pokračuje se v téže generaci jako v ročních mapách. Původní ukončený Land and Ocean produkt s názvem „Air Temperature over Sea Ice“ se nepřimíchává. Podle [oficiálního popisu nové metody](https://berkeleyearth.org/september-2026-temperature-update/) se nad mořským ledem extrapolují anomálie teploty vzduchu z pevniny; nad otevřeným oceánem jde o SST. [Datový přehled](https://berkeleyearth.org/data/). Produkt je předběžný; původní upozornění je v `original/docs/berkeley_hr_README.txt`. Původ a SHA-256 obou vstupů jsou zachovány v `original/provenance.json` a novém protokolu kontrol.

## Čas a chybějící data

Každý vstup se dekóduje na explicitní dvojice (rok, měsíc). Ověří se unikátnost, pořadí a navazování. Použije se průnik měsíců obou datových sad, nikoli stejné numerické indexy různě dlouhých zdrojů. Počátek a konec každého 12měsíčního okna jsou pro obě veličiny totožné.

Pro buňku g a okno i platí:

`A[i,g] = sum(d[m] * X[m,g], m=i…i+11) / sum(d[m], m=i…i+11) − reference[g]`.

Pokud chybí kterýkoli z 12 měsíců nebo reference, výsledek je NaN. Denominátor se nikdy nezkracuje na dostupné měsíce; NaN se nezaměňuje nulou. Úplnost místní buňky není podmínkou existence globálního časového okna: neúplná buňka je šedá, ostatní zůstávají platné. Roky přestupnosti určuje gregoriánský kalendář.

Okno má hranice `[začátek prvního měsíce, začátek měsíce po posledním)`. Střed je aritmetický časový půlící bod těchto hranic v UTC, včetně půldne pro lichý počet dní. NetCDF obsahuje CF čas i hranice, manifest také ISO časy, datum středu, měsíční rozsah a počet dní. Krok okna je jeden kalendářní měsíc. Je přesně 318−12+1 = 307 snímků.

## Geografické a barevné zobrazení

Středy buněk: šířka −89,5…89,5°, délka −179,5…179,5°, síť 180 × 360. Délky CERES se přeuspořádají z 0…360° na −180…180°, bez interpolace. Obě sítě musí být shodné s tolerancí 10⁻⁹ stupně.

Projekce je skutečná Mollweideova s centrálním poledníkem 0°. Inverzní rovnice jsou stejné jako v původním atlasu, kontrolované proti PROJ. Každý z 900 × 450 obrazových bodů mapy má ve sdílené tabulce přiřazenou skutečnou 1° buňku, nebo −1 mimo elipsu. Okraje −180° a +180° mají vlastní krajní sloupce; sever a jih vlastní polární řádky. Neprovádí se vyhlazování hodnot. Pobřeží Natural Earth 50m, verze 4.1.0, public domain, promítnuté PROJ; linie se při skoku délky přes 180° rozpojí. Žádné státní hranice ani geografická síť. Opaque černý pobřežní overlay je společný pro HTML i Python.

Paleta obsahuje deset modrých odstínů, jednu bílou přesně pro nulu a deset červených odstínů. Intervaly mají šířku L/10 pro každé znaménko. Na přesné vnitřní hranici k/10 L zůstává hodnota v méně sytém intervalu; hodnota těsně za hranicí postupuje do dalšího. Za ±L se přiřadí krajní barva. Chybějící hodnoty jsou RGB (210,214,220). Pouze tři číselné popisky: −L, 0, +L.

Automatické meze = nejmenší povolený krok ne menší než maximum absolutních hodnot celé zvolené řady, omezený horní i dolní mezí šoupátka. Nesledují každý snímek, aby barvy zůstávaly během přehrávání porovnatelné. Auto ASR a auto teploty jsou nezávislé. Export zmrazí skutečně účinné meze v okamžiku uložení JSON.

## Zobrazovací kopie a video

Plné výsledky jsou float64. Pro HTML i MP4 se ze stejných výsledků vytvoří identické little-endian float32 bloky, po 12 snímcích, gzip + bezztrátové base64 pro místní načtení přes skripty. Přiřazení barev Pythonem i JavaScriptem probíhá nad toutéž float32 hodnotou převedenou do float64 čísla; paleta a projekční tabulka jsou společné. Všechny zobrazovací bloky mají SHA-256. Bez kvantizace do barev, bez úprav výpočetních hodnot.

Prohlížeč používá Canvas 2D, dekomprimuje bloky asynchronně, přednačítá další a ukládá nejvýše pět bloků. Při změně snímku se obě pole přijmou společně; opožděný požadavek se zneplatní pořadovým číslem. Přehrávání nepřeskakuje měsíce ani při pomalejším vykreslování. Rychlost je horní požadovaná snímková frekvence, skutečná může být na pomalém zařízení nižší.

Python vykresluje stejnou scénu 1920 × 1080 a posílá nekomprimované RGB snímky do FFmpeg/libx264. MP4 má konstantní frekvenci, H.264, CRF 16 a yuv420p pro kompatibilitu. Každé okno se zapíše právě jednou, první i poslední včetně. Barevná komprese je ztrátová; přesná shoda mapových pixelů se kontroluje před kompresí a kvalita všech dekódovaných snímků zvlášť. Soubor `.frames.json` jednoznačně mapuje každý video snímek na původní okno a čas.

ASR má stejnou fyzikální definici jako v původním atlasu; vazba na albedo je podmíněna příchozím tokem. Toto rozšíření neinterpretuje příčiny změn ASR ani teploty.
