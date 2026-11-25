"""Compare Groq's hosted Whisper with local mlx-whisper on a real lecture clip, before switching.

Both run the real pipeline (LiveSession: 7 s windows, silence skipping, the names prompt,
owned_words), each building its prompts from its own transcript like a live session would.
Prints latency per window, how closely Groq's transcript matches mlx's (word error rate),
how far apart matching words' timestamps are, an estimated Groq cost, and a few differences.

Run from server/ with the venv active, on an Apple Silicon Mac (mlx is the baseline):
    python scripts/compare_stt.py ~/Downloads/lecture.m4a --title "Lecture 4: Glycolysis"
Needs GROQ_API_KEY in the repo-root .env. Any format macOS can read works (mp3, m4a, wav, ...):
afconvert, built into macOS, turns it into 16 kHz mono first, so ffmpeg isn't needed.
"""
import argparse
import asyncio
import io
import re
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from difflib import SequenceMatcher
from pathlib import Path

import httpx
import numpy as np
from dotenv import dotenv_values

from app.config import ROOT_ENV, settings
from app.stt.live import LiveSession
from app.stt.mlx import MlxWhisperTranscriber
from app.stt.transcriber import SAMPLE_RATE, Word

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"   # the same model as settings.stt_model, hosted
GROQ_PER_HOUR = 0.04                    # USD per audio hour from Groq's model page; check before relying on it
GROQ_MIN_BILLED_S = 10.0                # minimum billed per request, per an older Groq guide
CHUNK = SAMPLE_RATE * 5                 # the client uploads 5 s chunks (renderer.js CHUNK)


# --- audio ---

def load_audio(path: Path) -> np.ndarray:
    """Any audio file -> 16 kHz mono float32 in [-1, 1], via macOS's afconvert."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "clip.wav"
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", "-c", "1", str(path), str(wav)],
            check=True, capture_output=True,
        )
        with wave.open(str(wav)) as w:
            frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


def to_wav(samples: np.ndarray) -> bytes:
    """float32 samples -> 16-bit mono WAV bytes, what Groq's endpoint accepts."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return out.getvalue()


# --- transcribers ---

class GroqTranscriber:
    """Prototype of stt/groq.py: same methods as MlxWhisperTranscriber, over HTTPS."""

    def __init__(self, api_key: str, language: str = "en"):
        self._client = httpx.AsyncClient(timeout=30, headers={"Authorization": f"Bearer {api_key}"})
        self._language = language

    async def transcribe(self, samples: np.ndarray) -> str:
        return " ".join(w.text for w in await self.transcribe_words(samples))

    async def transcribe_words(self, samples: np.ndarray, prompt: str | None = None) -> list[Word]:
        data = {
            "model": GROQ_MODEL,
            "language": self._language,
            "response_format": "verbose_json",
            "timestamp_granularities[]": ["word"],
        }
        if prompt:
            data["prompt"] = prompt
        for attempt in range(5):
            res = await self._client.post(GROQ_URL, data=data, files={"file": ("window.wav", to_wav(samples), "audio/wav")})
            if res.status_code != 429:   # rate limited: wait as told, then retry
                break
            await asyncio.sleep(float(res.headers.get("retry-after", 2 ** attempt)))
        res.raise_for_status()
        body = res.json()
        if "words" not in body:
            sys.exit(f"Groq returned no word timestamps; response keys: {sorted(body)}")
        return [Word(w["start"], w["end"], w["word"].strip()) for w in body["words"] if w["word"].strip()]


class Timed:
    """Wraps a transcriber: records each window's audio length and how long the call took."""

    def __init__(self, inner):
        self.inner = inner
        self.calls: list[tuple[float, float]] = []   # (audio seconds, wall seconds)

    async def transcribe(self, samples):
        return await self.inner.transcribe(samples)

    async def transcribe_words(self, samples, prompt=None):
        start = time.perf_counter()
        words = await self.inner.transcribe_words(samples, prompt=prompt)
        self.calls.append((len(samples) / SAMPLE_RATE, time.perf_counter() - start))
        return words


async def run_session(transcriber, audio: np.ndarray, title: str | None) -> list[Word]:
    """Feeds the clip through a LiveSession in 5 s chunks, like the app does. Returns its words."""
    session = LiveSession(transcriber, title=title)
    words: list[Word] = []
    add = session.buffer.add
    session.buffer.add = lambda kept: (words.extend(kept), add(kept))   # the buffer keeps only 10 min
    for seq, start in enumerate(range(0, len(audio), CHUNK)):
        await session.add_chunk(seq, audio[start:start + CHUNK])
    await session.finish()
    return words


# --- comparing ---

def norm(text: str) -> str:
    """Lowercase, no punctuation: "Glycolysis," and "glycolysis" are the same word."""
    return re.sub(r"[^\w']+", "", text.lower())


def wer(reference: list[str], hypothesis: list[str]) -> float:
    """Word error rate: (substitutions + deletions + insertions) / reference length."""
    prev = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, 1):
        cur = [i]
        for j, hyp in enumerate(hypothesis, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ref != hyp)))
        prev = cur
    return prev[-1] / max(len(reference), 1)


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p * (len(ordered) - 1)))]


def report_latency(name: str, calls: list[tuple[float, float]]) -> None:
    walls = [wall for _, wall in calls]
    print(f"  {name:<5} median {statistics.median(walls):.2f}s   p95 {pct(walls, 0.95):.2f}s   "
          f"max {max(walls):.2f}s   ({len(walls)} windows)")


async def main():
    parser = argparse.ArgumentParser(description="Compare Groq's hosted Whisper with local mlx-whisper.")
    parser.add_argument("audio", type=Path, help="a lecture clip, 2-5 minutes; any format macOS can read")
    parser.add_argument("--title", help="the video title, used in the Whisper prompt like the app does")
    parser.add_argument("--examples", type=int, default=8, help="how many differences to print")
    args = parser.parse_args()

    key = dotenv_values(ROOT_ENV).get("GROQ_API_KEY")
    if not key:
        sys.exit(f"Set GROQ_API_KEY in {ROOT_ENV}")

    audio = load_audio(args.audio.expanduser())
    print(f"clip: {len(audio) / SAMPLE_RATE:.0f}s   title: {args.title!r}\n")

    mlx_inner = MlxWhisperTranscriber(model=settings.stt_model, language=settings.stt_language)
    print("loading the mlx model...")
    await mlx_inner.warm_up()   # so the first window's time isn't model loading
    mlx = Timed(mlx_inner)
    groq = Timed(GroqTranscriber(key, language=settings.stt_language))

    print("transcribing with mlx...")
    mlx_words = await run_session(mlx, audio, args.title)
    print("transcribing with groq...")
    groq_words = await run_session(groq, audio, args.title)

    print("\nLATENCY per window (a window is due every 5 s, so under ~2 s keeps up comfortably)")
    report_latency("mlx", mlx.calls)
    report_latency("groq", groq.calls)

    ref, hyp = [norm(w.text) for w in mlx_words], [norm(w.text) for w in groq_words]
    print(f"\nACCURACY  groq vs mlx word error rate: {wer(ref, hyp):.1%}   ({len(ref)} vs {len(hyp)} words)")
    print("  (mlx is the baseline, not the truth: a difference can be either one's mistake)")

    matcher = SequenceMatcher(None, ref, hyp, autojunk=False)
    gaps = [
        abs(mlx_words[a + k].start - groq_words[b + k].start)
        for a, b, size in matcher.get_matching_blocks() for k in range(size)
    ]
    if gaps:
        print(f"\nTIMESTAMPS  matching words' start times differ by median {statistics.median(gaps):.2f}s, "
              f"p95 {pct(gaps, 0.95):.2f}s, max {max(gaps):.2f}s")

    clip_s = len(audio) / SAMPLE_RATE
    billed = sum(max(seconds, GROQ_MIN_BILLED_S) for seconds, _ in groq.calls)
    per_hour = GROQ_PER_HOUR * billed / clip_s   # billed audio hours per lecture hour, times the rate
    print(f"\nCOST  ~{billed:.0f}s billed for {clip_s:.0f}s of audio "
          f"-> about ${per_hour:.3f} per lecture hour (estimate, check Groq's pricing page)")

    diffs = [op for op in matcher.get_opcodes() if op[0] != "equal"][:args.examples]
    if diffs:
        print(f"\nDIFFERENCES (first {len(diffs)})")
    for tag, a0, a1, b0, b1 in diffs:
        at = mlx_words[a0].start if a0 < len(mlx_words) else mlx_words[-1].end
        mlx_text = " ".join(w.text for w in mlx_words[a0:a1]) or "-"
        groq_text = " ".join(w.text for w in groq_words[b0:b1]) or "-"
        print(f"  {at:6.1f}s  mlx: {mlx_text!r:<40} groq: {groq_text!r}")


if __name__ == "__main__":
    asyncio.run(main())
