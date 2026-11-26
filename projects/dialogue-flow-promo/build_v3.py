# -*- coding: utf-8 -*-
"""Dialogue Flow — презентационное видео, версия 3 (концентрированная, ~65 с).

  python3 build_v3.py --src <все исходники> --out <папка> --music <sunday.ogg> [--alt <трек> ...] [--draft]

Исходники — обе папки Dropbox со всеми подпапками; имена как в Dropbox или короткие («31-10_17-00-53.mov»).
Ошибочная метка поворота −90° снимается на входе (-display_rotation 0), картинка не поворачивается.
Каждый фрагмент проверен по кадрам на провалы резкости (поиск автофокуса) и тёмные места.

Музыка: «Sunday Afternoon», Kistol (OpenGameArt), CC BY 3.0 — нейлоновая гитара, 65,7 с,
тихие переборы до ~37 с, затем плотнее, естественный конец. --alt собирает тот же монтаж с другим треком.
"""
import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
FPS = 25
W, H = 1920, 1080
FONT = HERE / "assets" / "Montserrat-ExtraBold.ttf"
FONT_TITLE = HERE / "assets" / "Montserrat-ExtraBold.ttf"

# Надписи: одно место для всех — левый нижний угол, левый край и низ блока закреплены.
TXT_SIZE, TXT_LH = 72, 88
TITLE_SIZE = 112
LEFT, BOTTOM = 124, 100
FADE = 0.4

MUSIC_IN = 0.0      # трек с начала: естественный вход
MUSIC_GAIN = "0dB"   # трек −18,6 LUFS: уже негромкий
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
    # Пространство встречи: несколько людей за столом, зал
    ("31-10 16 58 01", 0.3, 5.2, "neutral", False),  # 0 общий стол, рассказ с жестом
    ("07-11 17 11 01", 3.0, 5.0, "neutral", False),  # 1 зал у окна, группа
    # Выбор карт
    ("07-11 17 03 16", 0.3, 3.0, "warm", False),     # 2 карты на столе, за ними группа
    ("31-10 16 58 53", 0.1, 2.8, "warm", False),     # 3 женщина берёт карту
    ("31-10 17 32 24", 0.3, 4.4, "warm", False),     # 4 улыбки над картами
    ("07-11 16 53 19", 1.0, 3.2, "warm", False),     # 5 мужчина рассматривает карты
    # Разговоры в парах и в кругу — ближе, лица, жесты
    ("31-10 17 37 22", 0.0, 5.2, "cool_lift", False),  # 6 карта между собеседницами
    ("07-11 16 59 24", 2.0, 4.2, "warm", False),     # 7 мужчина с картой в руке объясняет, все смотрят
    ("31-10 17 03 00", 0.8, 4.5, "warm", False),     # 8 смеётся, показывая карту
    ("31-10 17 34 24", 1.2, 4.3, "warm", False),     # 9 рассказывает своё (резко до 5,6 с файла)
    ("07-11 17 30 07", 5.0, 5.0, "warm_lift", False),  # 10 увлечённый рассказ с жестами
    ("31-10 17 13 29", 7.5, 9.4, "warm", False),     # 11 широкий жест рассказа → собеседник слушает (один план)
    # Завершение: встреча целиком
    ("07-11 16 59 39", 6.0, 9.2, "neutral", True),   # 12 общий план встречи — финал
]

# Надписи: (номер кадра, сдвиг от начала кадра с, текст, длительность или None = по чтению).
TEXTS = [
    (0, 0.5, "We all hunger for\nheart-to-heart conversations", None),
    (1, 0.3, "But we don’t always find the time\nor a reason to begin", None),
    (4, 0.3, "Dialogue Cards\ngive us that reason", None),
    (6, 0.4, "An image can say\nwhat’s hard to put into words", None),
    (7, 0.3, "There’s no single right meaning", None),
    (8, 0.4, "You can talk about the picture", None),
    (9, 0.3, "Or share as much as you like", None),
    (10, 0.4, "A conversation can inspire us", None),
    (11, 0.4, "And help us see life differently", None),
    (11, 4.9, "To listen, and to feel heard", None),
    (12, 1.0, "Let’s make time for\nheart-to-heart conversations", None),
    (12, 5.4, "TITLE:Dialogue Flow", "end"),
]


def read_time(text: str) -> float:
    words = len(text.split())
    return max(3.0, min(4.4, 1.5 + 0.3 * words))


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
        ds.text((x, y + 2), ln, font=font, fill=(0, 0, 0, 110))
    sh = sh.filter(ImageFilter.GaussianBlur(4))
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
        sig = f"v3|{key}|{tin:.3f}|{frames}|{vf}|{crf}"
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
    final = out / ("dialogue_flow_v3" + ("_draft" if draft else "") + ".mp4")
    (out / "filter_v2.txt").write_text(";\n".join(fc), encoding="utf-8")
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex_script", str(out / "filter_v2.txt"),
         "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "medium" if draft else "slow",
         "-crf", "21" if draft else "17", "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{curlen:.3f}", str(final)])
    print(f"готово: {final} ({curlen:.2f} с)")
    edit_list(out / "edit_list_v3.md", starts, total, texts)
    return final


def tc(t):
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:05.2f}"


def edit_list(path, starts, total, texts):
    L = ["# Dialogue Flow v3 — монтажный лист", "",
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
    ap.add_argument("--alt", type=Path, nargs="*", default=[], help="тот же монтаж с другим треком")
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
        final = build(a.src, a.out, a.music, a.draft)
        dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                             "-of", "csv=p=0", str(final)]))
        for t in a.alt:
            v = final.with_name(final.stem + "_music-" + t.stem + ".mp4")
            run(["ffmpeg", "-v", "error", "-y", "-i", str(final), "-i", str(t), "-map", "0:v", "-map", "1:a",
                 "-c:v", "copy", "-af", f"atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,loudnorm=I=-19:TP=-2:LRA=9,"
                 f"afade=in:st=0:d=1.0,afade=out:st={dur - 3.0:.3f}:d=3.0", "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", "-t", f"{dur:.3f}", str(v)])
            print("вариант:", v)
