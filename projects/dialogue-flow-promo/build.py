# -*- coding: utf-8 -*-
"""Dialogue Flow — презентационное видео (горизонталь 16:9, до 90 с).

Воспроизводимый монтажный скрипт: план (блоки, исходники, точки входа, надписи) → ролик.
Только ffmpeg + Pillow, без Remotion.

Запуск:
  python3 build.py --src <папка с исходниками .mov> --out <рабочая папка> [--music <wav>] [--draft]

Исходники — файлы из Dropbox (папки «Лучшие»), имена как в Dropbox
(«Video 31-10-26, 17 00 53.mov») или короткие («31-10_17-00-53.mov»).
У всех исходников ошибочная метка поворота −90°: изображение в файле уже горизонтальное,
метка снимается на входе (-display_rotation 0), картинка не поворачивается.

Выход: <out>/dialogue_flow.mp4 (+ edit_list.md — монтажный лист с фактическими таймкодами).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
FPS = 25
W, H = 1920, 1080
FONT = HERE / "assets" / "Montserrat-Medium.ttf"
FONT_TITLE = HERE / "assets" / "Montserrat-SemiBold.ttf"

GAP = 0.45       # пауза без надписи между фразами
LEAD = 0.45      # от начала блока до первой надписи
FADE_TXT = 0.45  # появление / исчезновение надписи
DISSOLVE = 0.6   # мягкий переход (только там, где dissolve=True)

# Цвет: мягкая коррекция, без фильтров. warm — теплее (синеватый дневной/вечерний свет),
# cool — чуть холоднее и спокойнее (оранжевые лампы у дивана).
GRADE = {
    "neutral": "eq=saturation=0.98",
    "warm": "colortemperature=temperature=5600:mix=0.5,eq=saturation=1.0",
    "cool": "colortemperature=temperature=7400:mix=0.45,eq=saturation=0.92",
}

# Блоки сценария. clips: (исходник, вход в секундах, предпочтительная длина, цвет).
# Длина блока считается по надписям (время на чтение), клипы растягиваются/сжимаются
# пропорционально предпочтительной длине, но не дальше конца годного куска (max).
# pos: место надписи — "bl" низ-слева, "br" низ-справа, "tl" верх-слева, "tr" верх-справа.
BLOCKS = [
    dict(n=1, clips=[("31-10 17 00 53", 3.9, 1.6, 5.5, "neutral"),   # с 5,5 с в кадр входит рука
                     ("31-10 16 58 01", 0.3, 2.6, 5.3, "neutral")],
         texts=[("We all hunger for\nheart-to-heart conversations.", "bl")]),
    dict(n=2, clips=[("31-10 17 36 36", 0.4, 6.0, 15.6, "cool"),
                     ("31-10 17 44 10", 4.2, 4.8, 10.0, "cool")],
         texts=[("But in everyday life,\nwe don’t always find the time.", "bl"),
                ("Or a reason to begin.", "bl")]),
    dict(n=3, clips=[("31-10 17 32 40", 6.4, 4.6, 11.2, "warm"),
                     ("31-10 17 32 07", 0.3, 5.0, 6.9, "warm")],
         texts=[("Dialogue Cards give us\na starting point.", "tr"),
                ("Each image shows\na different side of life.", "tr")]),
    dict(n=4, clips=[("31-10 17 33 02", 0.0, 2.4, 2.4, "warm"),
                     ("31-10 17 41 12", 4.6, 10.0, 20.8, "cool")],
         texts=[("An image can express\nwhat’s hard to put into words.", "tr"),
                ("It can help us see\na situation differently.", "bl"),
                ("Or find an unexpected answer.", "bl")]),
    dict(n=5, clips=[("31-10 17 37 22", 0.0, 7.0, 11.8, "cool"),
                     ("31-10 17 03 07", 0.0, 5.6, 6.2, "neutral")],
         texts=[("You can simply talk\nabout the picture.", "tl"),
                ("Or share something\nfrom your own life.", "tl"),
                ("You choose how much to share.", "bl")]),
    dict(n=6, clips=[("31-10 17 34 24", 1.6, 5.0, 6.7, "neutral"),
                     ("31-10 17 41 48", 0.2, 8.0, 11.0, "cool")],
         texts=[("There’s no single right meaning\nfor a card.", "bl"),
                ("We can look at the same image\nand see very different stories.", "bl")]),
    dict(n=7, dissolve=True,
         clips=[("07-11 17 30 07", 3.6, 7.0, 11.8, "warm"),
                ("07-11 17 11 24", 4.4, 6.8, 11.3, "warm")],
         texts=[("Someone else’s story can help us\nsee our own life differently.", "bl"),
                ("A conversation can give us strength.", "bl"),
                ("And help us find meaning.", "bl")]),
    dict(n=8, clips=[("31-10 17 39 15", 1.4, 6.0, 10.9, "cool"),
                     ("07-11 17 36 32", 0.2, 6.0, 9.2, "neutral")],
         texts=[("That’s why we gather\nfor Dialogue Flow.", "bl"),
                ("To enjoy talking\nwith one another.", "bl"),
                ("To listen and feel heard.", "bl")]),
    dict(n=9, dissolve=True,
         clips=[("07-11 17 00 47", 4.4, 8.4, 12.9, "warm")],
         texts=[("Today, we make time\nfor that conversation.", "bl")],
         title="Dialogue Flow"),
]


def read_time(text: str) -> float:
    words = len(text.split())
    return max(3.0, min(4.7, 1.3 + 0.31 * words))


def src_path(src: Path, key: str) -> Path:
    d, t = key.split(" ", 1)              # "31-10", "17 00 53"
    dd, mm = d.split("-")
    cand = [src / f"Video {int(dd)}-{mm}-26, {t}.mov", src / f"{d}_{t.replace(' ', '-')}.mov"]
    for c in cand:
        if c.exists():
            return c
    sys.exit(f"нет исходника {key}: искал {', '.join(map(str, cand))}")


def plan():
    """Раскладка: сегменты видео и надписи на итоговой шкале (секунды)."""
    segs, texts = [], []
    t = 0.0
    for b in BLOCKS:
        overlap = DISSOLVE if b.get("dissolve") else 0.0
        start = t - overlap  # при мягком переходе блок начинается внутри предыдущего
        # длина по надписям
        dur = LEAD + sum(read_time(x) for x, _ in b["texts"]) + GAP * (len(b["texts"]) - 1)
        if b.get("title"):
            dur += GAP + 3.0
        dur += 0.4 + overlap
        # распределение по клипам
        pref = [c[2] for c in b["clips"]]
        k = dur / sum(pref)
        lens = [p * k for p in pref]
        caps = [c[3] - c[1] for c in b["clips"]]
        # не дальше конца годного куска: излишек отдаём соседям
        for _ in range(3):
            over = sum(max(0, l - cap) for l, cap in zip(lens, caps))
            lens = [min(l, cap) for l, cap in zip(lens, caps)]
            room = [cap - l for l, cap in zip(lens, caps)]
            if over <= 1e-6 or sum(room) <= 1e-6:
                break
            lens = [l + over * r / sum(room) for l, r in zip(lens, room)]
        if sum(lens) + 1e-3 < dur:
            print(f"! блок {b['n']}: не хватает материала {dur - sum(lens):.2f} с", file=sys.stderr)
        pos = start
        for (key, tin, _p, _mx, grade), ln in zip(b["clips"], lens):
            fr = round(ln * FPS)
            segs.append(dict(block=b["n"], key=key, tin=tin, frames=fr, grade=grade,
                             dissolve=(b.get("dissolve") and pos == start), start=pos))
            pos += fr / FPS
        # надписи
        tt = start + overlap + LEAD
        for i, (txt, where) in enumerate(b["texts"]):
            d = read_time(txt)
            texts.append(dict(block=b["n"], text=txt, pos=where, start=tt, dur=d))
            tt += d + GAP
        if b.get("title"):
            texts.append(dict(block=b["n"], text=b["title"], pos="title", start=tt, dur=None))
        t = pos
    total = t
    for x in texts:
        if x["dur"] is None:
            x["dur"] = total - x["start"]
    return segs, texts, total


# --- надписи: прозрачный PNG с мягким локальным градиентом ---

def text_png(text: str, where: str, out: Path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    mx, my = int(W * 0.065), int(H * 0.075)       # безопасные поля ~6–7 %
    if where == "title":
        font = ImageFont.truetype(str(FONT_TITLE), 92)
        tw = ImageDraw.Draw(img).textbbox((0, 0), text, font=font)
        w, h = tw[2] - tw[0], tw[3] - tw[1]
        x, y = (W - w) // 2, int(H * 0.80) - h // 2 - tw[1]   # внизу: не на лицах
        box = (x - 120, y - 70, x + w + 120, y + h + 90)
        lines_xy = [(x, y, text)]
        spacing = 0
    else:
        font = ImageFont.truetype(str(FONT), 54)
        lines = text.split("\n")
        d = ImageDraw.Draw(img)
        lh = 70
        widths = [d.textbbox((0, 0), ln, font=font)[2] for ln in lines]
        w, h = max(widths), lh * len(lines)
        right = where.endswith("r")
        top = where.startswith("t")
        x0 = W - mx - w if right else mx
        y0 = my if top else H - my - h
        lines_xy = [(x0 + (w - widths[i] if right else 0), y0 + i * lh, ln) for i, ln in enumerate(lines)]
        box = (x0 - 90, y0 - 60, x0 + w + 90, y0 + h + 50)
    # мягкая подложка: размытое тёмное пятно только под текстом
    shade = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shade).rounded_rectangle(box, radius=60, fill=120 if where != "title" else 140)
    shade = shade.filter(ImageFilter.GaussianBlur(55))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    dark.putalpha(shade)
    img = Image.alpha_composite(img, dark)
    # лёгкая тень у букв для читаемости
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ds = ImageDraw.Draw(sh)
    for x, y, ln in lines_xy:
        ds.text((x + 2, y + 3), ln, font=font, fill=(0, 0, 0, 150))
    sh = sh.filter(ImageFilter.GaussianBlur(3))
    img = Image.alpha_composite(img, sh)
    dt = ImageDraw.Draw(img)
    for x, y, ln in lines_xy:
        dt.text((x, y), ln, font=font, fill=(255, 255, 255, 255))
    img.save(out)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit("ffmpeg: " + r.stderr[-2000:])


def build(src: Path, out: Path, music: Path | None, draft: bool):
    out.mkdir(parents=True, exist_ok=True)
    (out / "seg").mkdir(exist_ok=True)
    (out / "txt").mkdir(exist_ok=True)
    segs, texts, total = plan()
    print(f"план: {len(segs)} фрагментов, {len(texts)} надписей, {total:.2f} с")
    if total > 90:
        sys.exit(f"длина {total:.2f} с больше 90 с — сократи надписи или паузы")

    # 1. фрагменты: вход по кадру, ровно, 1080p, цвет
    crf = "20" if draft else "12"
    for i, s in enumerate(segs):
        f = out / "seg" / f"{i:02d}.mp4"
        s["file"] = f
        vf = (f"scale={W}:{H}:flags=lanczos,fps={FPS},{GRADE[s['grade']]},format=yuv420p")
        sig = f"rot0|{s['key']}|{s['tin']:.3f}|{s['frames']}|{vf}|{crf}"
        meta = f.with_suffix(".sig")
        if f.exists() and meta.exists() and meta.read_text() == sig:
            continue
        run(["ffmpeg", "-v", "error", "-y", "-display_rotation:v:0", "0", "-ss", f"{s['tin']:.3f}",
             "-i", str(src_path(src, s["key"])), "-map", "0:v:0", "-frames:v", str(s["frames"]),
             "-vf", vf, "-c:v", "libx264", "-preset", "fast" if draft else "slow", "-crf", crf,
             "-an", str(f)])
        meta.write_text(sig)
        print(f"  фрагмент {i:02d} блок {s['block']} {s['key']} с {s['tin']:.2f} c, {s['frames']} к.")

    # 2. надписи
    for i, x in enumerate(texts):
        x["png"] = out / "txt" / f"{i:02d}.png"
        text_png(x["text"], x["pos"], x["png"])

    # 3. сборка
    inputs, fc = [], []
    for s in segs:
        inputs += ["-i", str(s["file"])]
    n = len(segs)
    # единая шкала времени у всех фрагментов — иначе xfade после concat не стыкуется
    for i in range(n):
        fc.append(f"[{i}:v]settb=1/{FPS * 512},setpts=PTS-STARTPTS,fps={FPS}[s{i}]")
    cur, curlen = "[s0]", segs[0]["frames"] / FPS
    for i in range(1, n):
        s = segs[i]
        if s["dissolve"]:
            fc.append(f"{cur}[s{i}]xfade=transition=fade:duration={DISSOLVE}:offset={curlen - DISSOLVE:.3f}[v{i}]")
            curlen += s["frames"] / FPS - DISSOLVE
        else:
            fc.append(f"{cur}[s{i}]concat=n=2:v=1:a=0,settb=1/{FPS * 512},fps={FPS}[v{i}]")
            curlen += s["frames"] / FPS
        cur = f"[v{i}]"
    for j, x in enumerate(texts):
        k = n + j
        d = x["dur"]
        inputs += ["-loop", "1", "-t", f"{d:.3f}", "-i", str(x["png"])]
        fade_out = "" if x["pos"] == "title" else f",fade=out:st={d - FADE_TXT:.3f}:d={FADE_TXT}:alpha=1"
        fc.append(f"[{k}:v]format=rgba,fade=in:st=0:d={FADE_TXT if x['pos'] != 'title' else 0.8}:alpha=1"
                  f"{fade_out},setpts=PTS+{x['start']:.3f}/TB[t{j}]")
        fc.append(f"{cur}[t{j}]overlay=0:0:eof_action=pass:format=auto[o{j}]")
        cur = f"[o{j}]"
    fc.append(f"{cur}fade=in:st=0:d=0.3,fade=out:st={curlen - 1.0:.3f}:d=1.0,format=yuv420p[vout]")
    amap = []
    if music:
        inputs += ["-i", str(music)]
        fc.append(f"[{n + len(texts)}:a]atrim=0:{curlen:.3f},asetpts=PTS-STARTPTS,volume=-4dB,"
                  f"afade=in:st=0:d=1.5,afade=out:st={curlen - 3.0:.3f}:d=3.0,"
                  f"aformat=sample_rates=48000:channel_layouts=stereo[aout]")
        amap = ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    name = "dialogue_flow" + ("_music" if music else "") + ("_draft" if draft else "") + ".mp4"
    final = out / name
    (out / "filter.txt").write_text(";\n".join(fc), encoding="utf-8")
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex_script", str(out / "filter.txt"),
         "-map", "[vout]", *amap, "-c:v", "libx264", "-preset", "medium" if draft else "slow",
         "-crf", "21" if draft else "17", "-profile:v", "high", "-pix_fmt", "yuv420p",
         "-r", str(FPS), "-movflags", "+faststart", "-t", f"{curlen:.3f}", str(final)])
    print(f"готово: {final} ({curlen:.2f} с)")
    write_edit_list(out / "edit_list.md", segs, texts, curlen, music)
    return final


def tc(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:05.2f}"


def write_edit_list(path: Path, segs, texts, total, music):
    L = ["# Dialogue Flow — монтажный лист", "",
         f"Итог: {tc(total)} ({total:.2f} с), 1920×1080, {FPS} к/с, H.264"
         + (", музыка AAC" if music else ", без звука"), "",
         "## Видео", "", "| # | Блок | Исходник | Вход | Выход | На шкале | Цвет |", "|---|---|---|---|---|---|---|"]
    for i, s in enumerate(segs):
        d = s["frames"] / FPS
        L.append(f"| {i + 1} | {s['block']} | Video {s['key'].split(' ')[0].replace('-', '-')}-26, "
                 f"{s['key'].split(' ', 1)[1]}.mov | {s['tin']:.2f} с | {s['tin'] + d:.2f} с | "
                 f"{tc(s['start'])}–{tc(s['start'] + d)} | {s['grade']} |"
                 + (" мягкий переход" if s["dissolve"] else ""))
    L += ["", "## Надписи", "", "| Блок | С | До | Текст |", "|---|---|---|---|"]
    for x in texts:
        L.append(f"| {x['block']} | {tc(x['start'])} | {tc(x['start'] + x['dur'])} | {x['text'].replace(chr(10), ' / ')} |")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--music", type=Path)
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--plan", action="store_true", help="только показать раскладку")
    a = ap.parse_args()
    if a.plan:
        segs, texts, total = plan()
        print(json.dumps(dict(total=total, segs=segs, texts=texts), ensure_ascii=False, indent=1, default=str))
    else:
        build(a.src, a.out, a.music, a.draft)
