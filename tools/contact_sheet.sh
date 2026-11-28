#!/usr/bin/env bash
# Контактный лист ролика: кадры с отметкой времени. Для просмотра картинки, а не намерений.
#   bash tools/contact_sheet.sh ролик.mp4 лист.jpg [кадров_в_секунду=1] [колонок=6] [от=0] [длительность=весь]
# Окна вокруг склейки (плотно): bash tools/contact_sheet.sh ролик.mp4 лист.jpg 12 6 28.5 2
set -euo pipefail
v="$1"; out="$2"; fps="${3:-1}"; cols="${4:-6}"; from="${5:-0}"; len="${6:-}"
font=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
[ -f "$font" ] || font=/System/Library/Fonts/Supplemental/Arial\ Bold.ttf
args=(-v error -y -ss "$from")
[ -n "$len" ] && args+=(-t "$len")
args+=(-i "$v" -vf "fps=${fps},scale=320:-1,drawtext=fontfile='${font}':text='%{pts\\:hms}':x=5:y=5:fontsize=16:fontcolor=yellow:box=1:boxcolor=black@0.55,tile=${cols}x20:padding=3" -frames:v 1 "$out")
ffmpeg "${args[@]}" && echo "лист: $out"
