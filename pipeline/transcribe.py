# -*- coding: utf-8 -*-
"""Word-level transcription: local Whisper by default, Deepgram optional.

Engines (--engine, or TRANSCRIBE_ENGINE in .env):
  auto           mlx-whisper on Apple Silicon if installed, else faster-whisper (default)
  faster-whisper local, free, CPU/GPU (CTranslate2), any OS
  mlx            local, free, Apple Silicon GPU (pip install mlx-whisper) — fastest on M-chips
  deepgram       paid API, needs DEEPGRAM_API_KEY

Usage: python transcribe.py <audio.wav> <out_dir> [language]
          [--engine ...] [--model large-v3-turbo] [--prompt "Имена, термины…"]
Writes: <engine>_raw.json, words.json, transcript.txt, utterances.txt
words.json format is the same for every engine: {i, w, pw, start, end, conf}.
"""
import argparse
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "large-v3-turbo")
MLX_MODELS = {  # short names -> mlx-community repos
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
}
# Bare form of a word for matching (Deepgram's `word`): lowercase, no punctuation.
_PUNCT = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _bare(token: str) -> str:
    return _PUNCT.sub("", token.strip()).lower() or token.strip().lower()


def _pick_engine(engine: str) -> str:
    if engine != "auto":
        return engine
    if sys.platform == "darwin" and platform.machine() == "arm64":
        try:
            import mlx_whisper  # noqa: F401
            return "mlx"
        except ImportError:
            pass
    return "faster-whisper"


def _load_audio(path: Path, sr: int = 16000):
    """Decode any audio/video to 16 kHz mono float32 via ffmpeg (no PyAV dependency)."""
    import numpy as np

    pcm = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-f", "s16le",
         "-ac", "1", "-ar", str(sr), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0


# --- engines: each returns (words[{word,pw,start,end,conf}], segments[{start,end,text}], raw) ---

def _faster_whisper(wav: Path, language: str, model: str, prompt: str | None):
    from faster_whisper import WhisperModel

    device = os.environ.get("WHISPER_DEVICE", "auto")
    compute = os.environ.get("WHISPER_COMPUTE", "default")  # int8 on CPU, float16 on CUDA
    wm = WhisperModel(model, device=device, compute_type=compute)
    seg_iter, info = wm.transcribe(
        _load_audio(wav),
        language=language,
        word_timestamps=True,
        initial_prompt=prompt,
        # each window decoded on its own: no runaway repetition loops on long recordings
        condition_on_previous_text=False,
        vad_filter=True,  # skip silence (no hallucinations there); timestamps stay absolute
        vad_parameters={"min_silence_duration_ms": 1000},
    )
    words, segs, raw = [], [], []
    for s in seg_iter:
        segs.append({"start": s.start, "end": s.end, "text": s.text.strip()})
        raw.append({"start": s.start, "end": s.end, "text": s.text,
                    "avg_logprob": s.avg_logprob, "no_speech_prob": s.no_speech_prob,
                    "words": [{"word": w.word, "start": w.start, "end": w.end,
                               "probability": w.probability} for w in (s.words or [])]})
        for w in s.words or []:
            words.append({"pw": w.word.strip(), "start": w.start, "end": w.end,
                          "conf": w.probability})
        print(f"  {s.end:8.1f}s / {info.duration:.0f}s", end="\r", flush=True)
    print()
    return words, segs, {"language": info.language, "duration": info.duration,
                         "segments": raw}


def _mlx(wav: Path, language: str, model: str, prompt: str | None):
    import mlx_whisper

    res = mlx_whisper.transcribe(
        str(wav),
        path_or_hf_repo=MLX_MODELS.get(model, model),
        language=language,
        word_timestamps=True,
        initial_prompt=prompt,
        condition_on_previous_text=False,
    )
    words, segs = [], []
    for s in res["segments"]:
        segs.append({"start": s["start"], "end": s["end"], "text": s["text"].strip()})
        for w in s.get("words", []):
            words.append({"pw": w["word"].strip(), "start": w["start"], "end": w["end"],
                          "conf": w.get("probability", 0.0)})
    return words, segs, res


def _deepgram(wav: Path, language: str, model: str, prompt: str | None):
    import requests

    key = os.environ.get("DEEPGRAM_API_KEY")
    if not key:
        raise RuntimeError("engine=deepgram, но нет DEEPGRAM_API_KEY в .env")
    params = {"model": "nova-3" if model == DEFAULT_MODEL else model, "language": language,
              "smart_format": "true", "punctuate": "true", "utterances": "true"}
    with open(wav, "rb") as f:
        resp = requests.post(
            "https://api.deepgram.com/v1/listen", params=params,
            headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"},
            data=f, timeout=900)
    resp.raise_for_status()
    data = resp.json()
    alt = data["results"]["channels"][0]["alternatives"][0]
    words = [{"word": w["word"], "pw": w.get("punctuated_word", w["word"]),
              "start": w["start"], "end": w["end"], "conf": w.get("confidence", 0.0)}
             for w in alt["words"]]
    segs = [{"start": u["start"], "end": u["end"], "text": u["transcript"]}
            for u in data["results"].get("utterances", [])]
    return words, segs, data


def _snap_to_speech(words: list, wav: Path) -> int:
    """Whisper word times drift ±0.2–0.4 s around pauses (a word "starts" in the silence
    before it). Snap word edges that fall into silence onto the nearest speech edge found
    by Silero VAD (bundled with faster-whisper). Returns how many edges moved."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except ImportError:
        return 0
    sr = 16000
    chunks = get_speech_timestamps(_load_audio(wav, sr), VadOptions(
        threshold=0.5, min_silence_duration_ms=150, speech_pad_ms=40))
    spans = [(c["start"] / sr, c["end"] / sr) for c in chunks]
    if not spans:
        return 0

    def inside(t):
        return any(a <= t <= b for a, b in spans)

    moved = 0
    for w in words:
        s, e = float(w["start"]), float(w["end"])
        if not inside(s):  # start in silence -> next speech onset inside the word
            nxt = [a for a, b in spans if s < a < e]
            if nxt:
                s, moved = nxt[0], moved + 1
        if not inside(e):  # end in silence -> last speech offset inside the word
            prv = [b for a, b in spans if s < b < e]
            if prv:
                e, moved = prv[-1], moved + 1
        w["start"], w["end"] = s, e
    return moved


ENGINES = {"faster-whisper": _faster_whisper, "mlx": _mlx, "deepgram": _deepgram}


def transcribe(wav_path: Path, out_dir: Path, language: str = "ru",
               engine: str | None = None, model: str | None = None,
               prompt: str | None = None):
    engine = _pick_engine(engine or os.environ.get("TRANSCRIBE_ENGINE", "auto"))
    model = model or DEFAULT_MODEL
    prompt = prompt or os.environ.get("WHISPER_PROMPT") or None
    print(f"transcribe: engine={engine} model={model if engine != 'deepgram' else 'nova-3'}")
    raw_words, segs, raw = ENGINES[engine](Path(wav_path), language, model, prompt)
    if engine != "deepgram":
        print(f"snap: {_snap_to_speech(raw_words, Path(wav_path))} word edges moved to speech")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{engine.replace('-', '_')}_raw.json").write_text(
        json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    words = []
    for w in raw_words:
        if not w["pw"]:
            continue
        words.append({
            "i": len(words),
            "w": w.get("word") or _bare(w["pw"]),
            "pw": w["pw"],
            "start": round(float(w["start"]), 3),
            "end": round(float(w["end"]), 3),
            "conf": round(float(w["conf"] or 0.0), 3),
        })
    (out_dir / "words.json").write_text(
        json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "transcript.txt").write_text(
        " ".join(s["text"] for s in segs).strip(), encoding="utf-8")
    (out_dir / "utterances.txt").write_text(
        "\n".join(f"[{s['start']:8.2f} - {s['end']:8.2f}] {s['text']}" for s in segs),
        encoding="utf-8")

    print(f"OK words={len(words)} last_end={words[-1]['end'] if words else 0:.2f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Транскрибация с пословными таймкодами")
    ap.add_argument("wav")
    ap.add_argument("out_dir")
    ap.add_argument("language", nargs="?", default="ru")
    ap.add_argument("--engine", choices=["auto", *ENGINES])
    ap.add_argument("--model", help=f"модель Whisper (по умолчанию {DEFAULT_MODEL})")
    ap.add_argument("--prompt", help="подсказка Whisper: имена, термины, стиль речи")
    a = ap.parse_args()
    transcribe(Path(a.wav), Path(a.out_dir), a.language, a.engine, a.model, a.prompt)
