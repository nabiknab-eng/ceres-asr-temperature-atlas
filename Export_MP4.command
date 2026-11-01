#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
  py=.venv/bin/python
elif [ -x ../../work/venv/bin/python ]; then
  py=../../work/venv/bin/python
else
  echo "První příprava Pythonu (vyžaduje internet pro instalaci závislostí)."
  python3 -m venv .venv
  py=.venv/bin/python
  "$py" -m pip install -r requirements_export.txt
fi
echo "Přetáhněte sem JSON stažený z atlasu a stiskněte Enter."
echo "Samotný Enter použije výchozí celé období, ±20 W/m², ±4 °C, 6 snímků/s."
IFS= read -r settings
if [ -z "$settings" ]; then
  settings=export_settings.json
else
  settings=$("$py" -c 'import shlex,sys; print(shlex.split(sys.argv[1])[0])' "$settings")
fi
output="exports/animace-$(date +%Y%m%d-%H%M%S).mp4"
"$py" export_mp4.py --settings "$settings" --output "$output"
echo "Hotovo: $PWD/$output"
echo "Stiskněte Enter pro zavření."
read -r
