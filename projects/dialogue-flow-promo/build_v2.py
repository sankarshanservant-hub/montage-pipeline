# -*- coding: utf-8 -*-
"""Dialogue Flow — презентационное видео, версия 2 (перемонтаж по замечаниям).

Воспроизводимый монтажный скрипт: план кадров и надписей → MP4. Только ffmpeg + Pillow.

  python3 build_v2.py --src <папка исходников> --out <рабочая папка> --music <inspiring.mp3> [--draft]

Исходники — файлы обеих папок Dropbox (все подпапки), имена как в Dropbox
(«Video 31-10-26, 17 00 53.mov») или короткие («31-10_17-00-53.mov»).
У всех исходников ошибочная метка поворота −90°: картинка в файле уже горизонтальная,
метка снимается на входе (-display_rotation 0), изображение не поворачивается.

Музыка: «Inspiring and optimistic Piano», Bogart VGM (OpenGameArt), CC BY 4.0.
Три части трека задают три части истории: тихо (контакт) → нарастание с 32,0 с
(карты и разные истории) → кульминация с 66,5 с (ценность общения, финал).
"""
import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
FPS = 25
W, H = 1920, 1080
FONT = HERE / "assets" / "Montserrat-SemiBold.ttf"
FONT_TITLE = HERE / "assets" / "Montserrat-Bold.ttf"

# Надписи: одно место для всех — левый нижний угол, левый край и низ блока закреплены.
TXT_SIZE, TXT_LH = 68, 84
TITLE_SIZE = 108
LEFT, BOTTOM = 124, 100
FADE = 0.4

MUSIC_IN = 2.0      # с какой секунды трека начинаем (начало мягкое, фраза не рвётся)
MUSIC_GAIN = "-5dB"  # трек −12,8 LUFS → около −18 LUFS: негромко под чтение
DISSOLVE = 0.7

# Цвет: мягко, без фильтров. lift — светлее для полутёмных планов,
# warm — теплее синеватый свет окна, cool — спокойнее оранжевые лампы.
GRADE = {
    "neutral": "eq=saturation=0.98",
    "warm": "colortemperature=temperature=5700:mix=0.45",
    "cool": "colortemperature=temperature=7300:mix=0.4,eq=saturation=0.93",
    "cool_lift": "colortemperature=temperature=7300:mix=0.4,eq=saturation=0.93:gamma=1.12",
    "warm_lift": "colortemperature=temperature=5700:mix=0.45,eq=gamma=1.10",
}

# Кадры по порядку: (исходник, вход с, длительность с, цвет, мягкий переход в этот кадр)
SHOTS = [
    # Часть 1 — контакт и интерес (музыка тихая, 0–30 с)
    ("31-10 17 36 36", 8.0, 6.0, "cool", False),     # 0 две женщины смеются на светлом диване
    ("31-10 16 58 01", 0.3, 5.1, "neutral", False),  # 1 общий стол: рассказ с жестом, лица
    ("07-11 17 11 01", 0.3, 7.0, "neutral", False),  # 2 пустой зал под лампами → люди у окна
    ("31-10 17 07 34", 0.4, 5.6, "neutral", False),  # 3 мужчина у витрины, тихо, перед разговором
    ("07-11 17 03 16", 0.3, 6.3, "warm", False),     # 4 карты на столе, за ними группа (без надписи)
    # Часть 2 — карты как повод (нарастание с 30 с)
    ("31-10 16 58 53", 0.1, 2.8, "warm", False),     # 5 женщина берёт карту со стола у окна
    ("31-10 16 59 25", 0.6, 3.6, "warm", False),     # 6 мужчина идёт вдоль разложенных карт
    ("31-10 17 32 24", 0.3, 4.4, "warm", False),     # 7 улыбки у стола с картами
    ("07-11 16 53 19", 1.0, 4.4, "warm", False),     # 8 мужчина рассматривает карты (без надписи)
    ("31-10 17 37 22", 0.0, 5.4, "cool_lift", False),  # 9 карта между двумя собеседницами
    ("07-11 17 21 49", 6.0, 3.9, "warm", False),     # 10 группа, карты на переднем плане (без надписи)
    ("31-10 17 03 00", 0.8, 5.0, "warm", False),     # 11 смеётся, показывая карту
    ("31-10 17 34 24", 1.4, 5.0, "warm", False),     # 12 мужчина рассказывает о своём, его слушают
    # Часть 3 — разные истории и ценность общения (кульминация с 64,5 с)
    ("07-11 17 30 07", 5.0, 5.5, "warm_lift", False),  # 13 участник в красном увлечённо рассказывает
    ("31-10 17 35 32", 4.5, 4.8, "warm", False),     # 14 мужчина в чёрном говорит, его слушают
    ("07-11 16 59 24", 2.0, 4.5, "warm", False),     # 15 группа 7.11: объясняет, все повернулись к нему
    ("31-10 17 12 51", 0.4, 5.4, "warm", False),     # 16 внимательное слушание (мужчина в полоску)
    ("07-11 16 59 39", 6.0, 7.8, "neutral", True),   # 17 общий план встречи — финал
]

# Надписи: (номер кадра, сдвиг от начала кадра с, текст, длительность или None = по чтению).
# Только там, где левый нижний угол не закрывает лица, руки и карты.
TEXTS = [
    (0, 0.9, "We all hunger for\nheart-to-heart conversations", None),
    (2, 3.2, "But in everyday life,\nwe don’t always find the time", None),
    (3, 1.6, "Or a reason to begin", None),
    (7, 0.5, "Dialogue Cards\ngive us that reason", None),
    (9, 0.6, "An image can say\nwhat’s hard to put into words", None),
    (11, 0.5, "You can simply talk\nabout the picture", None),
    (12, 0.4, "Or share something of your own —\nit’s up to you", None),
    (13, 0.5, "No single right meaning,\nmany different stories", None),
    (14, 0.4, "A conversation can inspire us\nand give us strength", None),
    (15, 0.4, "And help us see\nthings differently", None),
    (16, 0.6, "To listen,\nand to feel heard", None),
    (17, 0.9, "Let’s make time for\nheart-to-heart conversations", None),
    (17, 5.0, "TITLE:Dialogue Flow", "end"),
]


def read_time(text: str) -> float:
    words = len(text.split())
    return max(3.0, min(4.6, 1.5 + 0.32 * words))


def src_path(src: Path, key: str) -> Path:
    d, t = key.split(" ", 1)
    dd, mm = d.split("-")
    for c in (src / f"Video {int(dd)}-{mm}-26, {t}.mov", src / f"{d}_{t.replace(' ', '-')}.mov"):
        if c.exists():
            return c
    sys.exit(f"нет исходника {key} в {src}")


def plan():
    pos, starts = 0.0, []
    for i, (_k, _tin, dur, _g, diss) in enumerate(SHOTS):
        if diss and i:
            pos -= DISSOLVE
        starts.append(pos)
        pos += round(dur * FPS) / FPS
    total = pos
    texts = []
    for si, off, txt, d in TEXTS:
        t0 = starts[si] + off
        title = txt.startswith("TITLE:")
        dur = (total - t0) if d == "end" else (d or read_time(txt))
        texts.append(dict(shot=si, start=t0, dur=dur, text=txt[6:] if title else txt, title=title))
    # проверка: надписи не налезают друг на друга
    for a, b in zip(texts, texts[1:]):
        if a["start"] + a["dur"] > b["start"] - 0.2:
            print(f"! надпись «{a['text'][:30]}» налезает на следующую", file=sys.stderr)
    return starts, total, texts


def text_png(text: str, title: bool, out: Path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    font = ImageFont.truetype(str(FONT_TITLE if title else FONT), TITLE_SIZE if title else TXT_SIZE)
    lh = int(TITLE_SIZE * 1.15) if title else TXT_LH
    lines = text.split("\n")
    asc, desc = font.getmetrics()
    # низ блока закреплён: последняя строка всегда на одной высоте
    y_last = H - BOTTOM - asc
    pos = [(LEFT, y_last - (len(lines) - 1 - i) * lh, ln) for i, ln in enumerate(lines)]
    # лёгкая мягкая тень — только чтобы буквы не растворялись на светлом; без подложек
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ds = ImageDraw.Draw(sh)
    for x, y, ln in pos:
        ds.text((x, y + 2), ln, font=font, fill=(0, 0, 0, 85))
    sh = sh.filter(ImageFilter.GaussianBlur(5))
    img = Image.alpha_composite(img, sh)
    d = ImageDraw.Draw(img)
    for x, y, ln in pos:
        d.text((x, y), ln, font=font, fill=(255, 252, 246, 255))
    img.save(out)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit("ffmpeg: " + r.stderr[-2500:])


def build(src: Path, out: Path, music: Path, draft: bool):
    out.mkdir(parents=True, exist_ok=True)
    (out / "seg").mkdir(exist_ok=True)
    (out / "txt").mkdir(exist_ok=True)
    starts, total, texts = plan()
    print(f"план: {len(SHOTS)} кадров, {len(texts)} надписей, {total:.2f} с")
    crf = "20" if draft else "12"
    files = []
    for i, (key, tin, dur, grade, _d) in enumerate(SHOTS):
        f = out / "seg" / f"{i:02d}.mp4"
        frames = round(dur * FPS)
        vf = f"scale={W}:{H}:flags=lanczos,fps={FPS},{GRADE[grade]},format=yuv420p"
        sig = f"v2|{key}|{tin:.3f}|{frames}|{vf}|{crf}"
        meta = f.with_suffix(".sig")
        if not (f.exists() and meta.exists() and meta.read_text() == sig):
            run(["ffmpeg", "-v", "error", "-y", "-display_rotation:v:0", "0", "-ss", f"{tin:.3f}",
                 "-i", str(src_path(src, key)), "-map", "0:v:0", "-frames:v", str(frames), "-vf", vf,
                 "-c:v", "libx264", "-preset", "fast" if draft else "slow", "-crf", crf, "-an", str(f)])
            meta.write_text(sig)
            print(f"  кадр {i:02d} {key} с {tin:.2f} с, {frames} к.")
        files.append((f, frames))
    for j, x in enumerate(texts):
        x["png"] = out / "txt" / f"{j:02d}.png"
        text_png(x["text"], x["title"], x["png"])

    inputs, fc = [], []
    for f, _ in files:
        inputs += ["-i", str(f)]
    n = len(files)
    for i in range(n):
        fc.append(f"[{i}:v]settb=1/{FPS * 512},setpts=PTS-STARTPTS,fps={FPS}[s{i}]")
    cur, curlen = "[s0]", files[0][1] / FPS
    for i in range(1, n):
        if SHOTS[i][4]:
            fc.append(f"{cur}[s{i}]xfade=transition=fade:duration={DISSOLVE}:offset={curlen - DISSOLVE:.3f}[v{i}]")
            curlen += files[i][1] / FPS - DISSOLVE
        else:
            fc.append(f"{cur}[s{i}]concat=n=2:v=1:a=0,settb=1/{FPS * 512},fps={FPS}[v{i}]")
            curlen += files[i][1] / FPS
        cur = f"[v{i}]"
    for j, x in enumerate(texts):
        k = n + j
        d = x["dur"]
        inputs += ["-loop", "1", "-t", f"{d:.3f}", "-i", str(x["png"])]
        fo = "" if x["title"] else f",fade=out:st={d - FADE:.3f}:d={FADE}:alpha=1"
        fc.append(f"[{k}:v]format=rgba,fade=in:st=0:d={FADE if not x['title'] else 0.6}:alpha=1{fo},"
                  f"setpts=PTS+{x['start']:.3f}/TB[t{j}]")
        fc.append(f"{cur}[t{j}]overlay=0:0:eof_action=pass:format=auto[o{j}]")
        cur = f"[o{j}]"
    fc.append(f"{cur}fade=in:st=0:d=0.4,fade=out:st={curlen - 1.2:.3f}:d=1.2,format=yuv420p[vout]")
    m = n + len(texts)
    inputs += ["-ss", f"{MUSIC_IN}", "-i", str(music)]
    fc.append(f"[{m}:a]atrim=0:{curlen:.3f},asetpts=PTS-STARTPTS,volume={MUSIC_GAIN},"
              f"afade=in:st=0:d=1.2,afade=out:st={curlen - 1.6:.3f}:d=1.6,"
              f"aformat=sample_rates=48000:channel_layouts=stereo[aout]")
    final = out / ("dialogue_flow_v2" + ("_draft" if draft else "") + ".mp4")
    (out / "filter_v2.txt").write_text(";\n".join(fc), encoding="utf-8")
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex_script", str(out / "filter_v2.txt"),
         "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "medium" if draft else "slow",
         "-crf", "21" if draft else "17", "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{curlen:.3f}", str(final)])
    print(f"готово: {final} ({curlen:.2f} с)")
    edit_list(out / "edit_list_v2.md", starts, total, texts)
    return final


def tc(t):
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:05.2f}"


def edit_list(path, starts, total, texts):
    L = ["# Dialogue Flow v2 — монтажный лист", "",
         f"Итог: {tc(total)} ({total:.2f} с), 1920×1080, {FPS} к/с, H.264 + AAC (музыка с {MUSIC_IN:.1f} с трека)", "",
         "## Кадры", "", "| # | Исходник | Вход | Выход | На шкале | Цвет |", "|---|---|---|---|---|---|"]
    for i, ((key, tin, dur, grade, diss), st) in enumerate(zip(SHOTS, starts)):
        d = round(dur * FPS) / FPS
        dd, t = key.split(" ", 1)
        L.append(f"| {i + 1} | Video {dd}-26, {t}.mov | {tin:.2f} с | {tin + d:.2f} с | "
                 f"{tc(st)}–{tc(st + d)} | {grade}{' · мягкий переход' if diss else ''} |")
    L += ["", "## Надписи", "", "| С | До | Текст |", "|---|---|---|"]
    for x in texts:
        L.append(f"| {tc(x['start'])} | {tc(x['start'] + x['dur'])} | {x['text'].replace(chr(10), ' / ')} |")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--music", type=Path)
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--plan", action="store_true")
    a = ap.parse_args()
    if a.plan:
        starts, total, texts = plan()
        print(f"всего {total:.2f} с")
        for i, s in enumerate(starts):
            print(f"{i:2d} {tc(s)} {SHOTS[i][0]}")
        for x in texts:
            print(f"   {tc(x['start'])} +{x['dur']:.1f} {x['text'].replace(chr(10), ' / ')}")
    else:
        build(a.src, a.out, a.music, a.draft)
