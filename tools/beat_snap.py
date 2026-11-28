# -*- coding: utf-8 -*-
"""Подгонка склеек под доли музыки.

  python3 tools/beat_snap.py --music трек.mp3 --cuts 5.2,10.2,13.2,... [--max-shift 0.3] [--offset 0.0]

Берёт запланированные времена склеек (секунды ролика) и предлагает сдвиг каждой на ближайшую долю трека,
если для этого не нужно двигать её больше --max-shift. Печатает таблицу и итоговые длины планов —
их остаётся перенести в SHOTS билд-скрипта (длительность плана = разность соседних склеек).

--offset: через сколько секунд после начала ролика стартует трек (если музыка входит не с нуля).
Темп и фаза оцениваются грубо (tools/film_check.py → beat_grid): для живой акустики оценка может ошибаться
вдвое, поэтому результат нужно проверить на слух. Ничего не меняет, только печатает.

Правила (docs/DIRECTING.md §6): склейка на долю — не на каждую; «одно действие — одна склейка».
Склейки, у которых сдвиг больше допуска, остаются как были и помечаются «—».
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from film_check import beat_grid  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--music", required=True)
    ap.add_argument("--cuts", required=True, help="склейки в секундах через запятую (без 0 и без конца)")
    ap.add_argument("--max-shift", type=float, default=0.3)
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--half", action="store_true", help="сетка вдвое реже (доли такта вместо ударов)")
    a = ap.parse_args()

    T, ph, bpm = beat_grid(a.music)
    if a.half:
        T *= 2
    cuts = [float(x) for x in a.cuts.split(",")]
    print(f"темп ≈ {bpm:.0f} уд/мин, шаг сетки {T:.3f} с, фаза {ph:.2f} с, допуск сдвига {a.max_shift:.2f} с\n")
    print(f"{'склейка':>8} {'доля':>8} {'сдвиг':>7}")
    snapped, prev = [], 0.0
    for c in cuts:
        t = c - a.offset                       # время в треке
        k = round((t - ph) / T)
        nearest = ph + k * T
        d = nearest - t
        if abs(d) <= a.max_shift:
            new = round(c + d, 2)
            mark = f"{d:+.2f}"
        else:
            new, mark = c, "—"
        if new - prev < 1.2:                   # не создавать суету
            new, mark = c, "—"
        snapped.append(new)
        prev = new
        print(f"{c:8.2f} {nearest + a.offset:8.2f} {mark:>7}")
    L = [round(b - a_, 2) for a_, b in zip([0.0] + snapped, snapped)]
    print("\nновые склейки:", ",".join(f"{x:.2f}" for x in snapped))
    print("длины планов:", " ".join(f"{x:.1f}" for x in L), "(последний план — до конца ролика)")
    hit = sum(1 for c, n in zip(cuts, snapped) if n != c)
    print(f"сдвинуто {hit} из {len(cuts)}")


if __name__ == "__main__":
    main()
