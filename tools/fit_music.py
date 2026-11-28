# -*- coding: utf-8 -*-
"""Подбор куска трека под длину ролика так, чтобы настоящий конец трека пришёлся на конец ролика.

  python3 tools/fit_music.py трек.mp3 --film 64.7 --out music_fit.wav [--lufs -19] [--fade-in 1.2]
  python3 tools/fit_music.py трек.mp3 --film 64.7 --list      # только показать, где конец трека

Ничего не режет и не склеивает внутри: берётся ОДИН непрерывный кусок трека, оканчивающийся там, где трек
сам заканчивается (хвост тишины отсекается, затухание сохраняется), и длиной ровно с ролик.
Если трек короче ролика — скажет об этом (тогда нужен другой трек, а не петля: петли слышны).
Если трек длиннее — ролик начнётся «с середины» трека; --start-near-section ищет место, где громкость
вырастает (вход куплета/фразы), в пределах ±3 с от нужного старта, чтобы начало не было случайным.
"""
import argparse
import re
import subprocess
import sys

import numpy as np


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def dur(f):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]).stdout)


def real_end(f, d):
    """Конец звучащей части: до тишины в хвосте (порог −50 дБ, ≥0.4 с)."""
    r = run(["ffmpeg", "-hide_banner", "-i", f, "-af", "silencedetect=n=-50dB:d=0.4", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", r.stderr)]
    tail = [s for s in starts if s > d - 12]
    return min(tail) + 0.6 if tail else d          # оставляем 0.6 с затухания


def rms_curve(f, step=0.5):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float64)
    n = int(8000 * step)
    return [20 * np.log10(np.sqrt(np.mean(a[i:i + n] ** 2)) + 1) for i in range(0, len(a) - n, n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("track")
    ap.add_argument("--film", type=float, required=True, help="длина ролика, с")
    ap.add_argument("--out")
    ap.add_argument("--lufs", type=float, default=-19.0)
    ap.add_argument("--fade-in", type=float, default=1.2)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--start-near-section", action="store_true")
    a = ap.parse_args()

    D = dur(a.track)
    end = real_end(a.track, D)
    print(f"трек {D:.1f} с; звучит до {end:.1f} с (хвост тишины {D - end:.1f} с); ролик {a.film:.1f} с")
    if end < a.film - 0.2:
        sys.exit(f"трек короче ролика на {a.film - end:.1f} с: нужен другой трек (петля слышна)")
    start = end - a.film
    if a.start_near_section and start > 3:
        c = rms_curve(a.track)
        lo, hi = int(max(0, (start - 3) / 0.5)), int(min(len(c) - 2, (start + 3) / 0.5))
        best = max(range(lo, hi), key=lambda i: c[i + 1] - c[i])
        print(f"старт сдвинут к ближайшему подъёму громкости: {start:.1f} → {best * 0.5:.1f} с "
              f"(тогда конец трека придётся на {best * 0.5 + a.film:.1f} с, а не на {end:.1f}); проверь на слух")
        start = best * 0.5
    print(f"берём {start:.2f}–{start + a.film:.2f} с трека")
    if a.list or not a.out:
        return
    af = (f"loudnorm=I={a.lufs}:TP=-2:LRA=11,afade=in:st=0:d={a.fade_in},"
          f"afade=out:st={a.film - 1.2:.2f}:d=1.2")
    r = run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{a.film:.3f}", "-i", a.track,
             "-af", af, "-ar", "48000", "-ac", "2", a.out])
    if r.returncode:
        sys.exit(r.stderr[-800:])
    print("записано:", a.out)


if __name__ == "__main__":
    main()
