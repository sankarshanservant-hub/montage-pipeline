# -*- coding: utf-8 -*-
"""Проверка готового ролика по цифрам — до того, как показывать человеку.

  python3 tools/film_check.py ролик.mp4 [--music трек.mp3] [--cuts 5.2,10.2,...]

Меряет то, что глазом не видно, но что отличает монтаж «по шаблону» от монтажа с решением:
  1. длины планов и разгон: темп к кульминации должен нарастать, а не быть ровным;
  2. где самый короткий план и где пик ролика (ориентир: 60–75 % длины);
  3. попадание склеек в долю музыки (если дан трек): случайные склейки дают ~40 %, решённые — 70 % и выше;
  4. замершее время (кадры почти не меняются) — для живых съёмок обычно 0;
  5. громкость: интегральная и диапазон (LRA); ровная «стена» звука — признак музыки-обоев;
  6. «арка» звука: громкость по 5-секундным окнам; тихая тишина перед поворотом и подъём к кульминации;
  7. чёрные кадры внутри ролика и тишина в конце.

Склейки берутся из --cuts (секунды, через запятую; удобно из монтажного листа) или находятся сами по смене сцены.
Идея набора проверок — из открытых проектов motion-video-kit (MIT) и motionmaxxing (Apache-2.0); код написан заново.
Нужны ffmpeg и numpy. Ничего не меняет, только печатает.
"""
import argparse
import re
import subprocess
import sys

import numpy as np


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def duration(f):
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]).stdout)


def detect_cuts(f, thr=0.28):
    r = sh(["ffmpeg", "-hide_banner", "-i", f, "-vf", f"select='gt(scene,{thr})',showinfo", "-an", "-f", "null", "-"])
    t = [float(m.group(1)) for m in re.finditer(r"pts_time:([0-9.]+)", r.stderr)]
    out = []
    for x in t:  # склейка и растворение дают несколько соседних срабатываний
        if not out or x - out[-1] > 0.8:
            out.append(round(x, 2))
    return out


def frozen(f, th=0.35):
    r = sh(["ffmpeg", "-hide_banner", "-i", f, "-vf",
            "fps=10,scale=320:-1,format=gray,tblend=all_mode=difference,signalstats,"
            "metadata=print:key=lavfi.signalstats.YAVG", "-an", "-f", "null", "-"])
    v = [float(x) for x in re.findall(r"YAVG=([0-9.]+)", r.stderr)]
    return sum(1 for x in v if x < th) / 10.0, len(v) / 10.0


def loud(f):
    r = sh(["ffmpeg", "-hide_banner", "-i", f, "-af", "ebur128=peak=true", "-vn", "-f", "null", "-"])
    g = lambda k: (re.search(rf"^\s+{k}:\s+(-?[0-9.]+)", r.stderr, re.M) or [None, "nan"])[1]
    return float(g("I")), float(g("LRA"))


def windows(f, step=5.0):
    """Громкость по окнам (RMS, дБ) — форма «арки» звука."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float64)
    if a.size == 0:
        return []
    n = int(8000 * step)
    return [20 * np.log10(np.sqrt(np.mean(a[i:i + n] ** 2)) + 1) for i in range(0, len(a), n) if len(a[i:i + n]) > n // 2]


def beat_grid(music):
    """Грубая оценка темпа и фазы по потоку спектра. Возвращает (период, фаза)."""
    sr, hop, fr = 22050, 256, 1024
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", music, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, np.float32)
    n = (len(x) - fr) // hop
    w = np.hanning(fr)
    S = np.array([np.abs(np.fft.rfft(x[i * hop:i * hop + fr] * w)) for i in range(n)])
    flux = np.maximum(0, np.diff(np.log1p(S * 10), axis=0)).sum(1)
    flux = (flux - flux.mean()) / (flux.std() + 1e-9)
    fps = sr / hop
    ac = np.correlate(flux, flux, "full")[len(flux) - 1:]
    cand = []
    for bpm in np.arange(55, 150, 0.5):
        lag = fps * 60 / bpm
        i2 = int(round(lag * 2))
        cand.append((ac[int(round(lag))] + (0.5 * ac[i2] if i2 < len(ac) else 0), bpm))
    bpm = max(cand)[1]
    if bpm > 110:          # автокорреляция часто даёт двойной темп; для живой акустики берём половину
        bpm /= 2
    T = 60 / bpm
    ph = max(np.arange(0, T, 0.01),
             key=lambda p: sum(flux[int(t * fps)] for t in np.arange(p, len(flux) / fps - 0.1, T) if int(t * fps) < len(flux)))
    return T, ph, bpm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--music")
    ap.add_argument("--cuts", help="секунды склеек через запятую (иначе ищутся сами)")
    ap.add_argument("--tol", type=float, default=0.07, help="допуск попадания в долю, с")
    a = ap.parse_args()

    D = duration(a.video)
    cuts = [float(x) for x in a.cuts.split(",")] if a.cuts else detect_cuts(a.video)
    edges = [0.0] + cuts + [D]
    L = np.diff(edges)
    print(f"{a.video}: {D:.1f} с, склеек {len(cuts)}{'' if a.cuts else ' (найдены сами)'}")
    if len(L) < 3:
        print("мало планов для анализа")
        return

    print("\n1. ПЛАНЫ И РАЗГОН")
    print("   длины, с:", " ".join(f"{x:.1f}" for x in L))
    h = len(L) // 2
    fa, fb = L[:h].mean(), L[h:].mean()
    print(f"   среднее: первая половина {fa:.1f} с, вторая {fb:.1f} с; мин {L.min():.1f}, макс {L.max():.1f}, разброс ×{L.max() / max(L.min(), .1):.1f}")
    body = L[:-1]                       # финальный общий план может быть длинным по замыслу
    peak_t = edges[int(np.argmin(body))] + body.min() / 2
    print(f"   самый короткий план (кандидат в пик) около {peak_t:.0f} с = {100 * peak_t / D:.0f} % длины (ориентир 60–75 %)")
    flags = []
    if fb >= fa * 0.95:
        flags.append("нет разгона: вторая половина не короче первой")
    if L.max() / max(L.min(), .1) < 2.2:
        flags.append("планы почти одной длины: нет ритмического рисунка")
    if len(L) > 3 and np.std(L) / L.mean() < 0.25:
        flags.append("ровный темп: коэффициент вариации длин < 0.25")
    if L[-1] > 7:
        flags.append(f"финальный план {L[-1]:.1f} с — затянут (после главной фразы смотреть не на что)")

    if a.music:
        T, ph, bpm = beat_grid(a.music)
        off = np.array([min((c - ph) % T, T - (c - ph) % T) for c in cuts])
        ok = (off < a.tol).mean()
        chance = 2 * a.tol / T
        print(f"\n3. СКЛЕЙКИ И МУЗЫКА   (темп ≈ {bpm:.0f} уд/мин, оценка грубая; допуск {a.tol * 1000:.0f} мс)")
        print(f"   в долю: {ok * 100:.0f} % склеек; случайные дали бы ≈{chance * 100:.0f} %")
        if ok < chance + 0.2:
            flags.append("склейки не связаны с музыкой (не лучше случайных)")

    fz, tot = frozen(a.video)
    print(f"\n4. ЗАМЕРШЕЕ ВРЕМЯ: {fz:.1f} с из {tot:.0f} (допустимо ≤ 1 с на 30 с)")
    if fz > tot / 30:
        flags.append("слишком много неподвижных кадров")

    I, LRA = loud(a.video)
    w = windows(a.video)
    print(f"\n5. ГРОМКОСТЬ: {I:.1f} LUFS, диапазон LRA {LRA:.1f} LU (для тёплой музыки норма 1.5–4)")
    if w:
        span = max(w) - min(w)
        print("6. АРКА ЗВУКА по 5 с, дБ:", " ".join(f"{x:.0f}" for x in w), f"| размах {span:.1f} дБ")
        if span < 4:
            flags.append("звук ровный как обои: размах по окнам < 4 дБ — нет ни подъёма, ни паузы перед поворотом")
        if w[-1] > max(w) - 1 and D > 20:
            flags.append("звук не затухает к концу — проверь, что финал музыки приходится на последний кадр")

    r = sh(["ffmpeg", "-hide_banner", "-i", a.video, "-vf", "blackdetect=d=0.2:pix_th=0.08", "-an", "-f", "null", "-"])
    blacks = [(float(s), float(e)) for s, e in re.findall(r"black_start:([0-9.]+) black_end:([0-9.]+)", r.stderr)]
    inner = [b for b in blacks if b[0] > 0.6 and b[1] < D - 0.1]
    print(f"7. ЧЁРНЫЕ КАДРЫ внутри ролика: {inner or 'нет'}")
    if inner:
        flags.append(f"чёрные провалы {inner}")

    print("\nИТОГ:", "замечаний нет" if not flags else "")
    for f in flags:
        print("  ✗", f)
    print("\nЦифры не заменяют просмотра: после них — контактный лист и свежий «критик» (docs/DIRECTING.md, §8).")


if __name__ == "__main__":
    sys.exit(main())
