import asyncio
import io
import wave

import httpx
import numpy as np

from app.stt.transcriber import SAMPLE_RATE, TranscriptionError, Word


GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MAX_RETRY_WAIT_S = 3.0

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


class GroqWhisperTranscriber:
    def __init__(self, api_key: str, model: str="whisper-large-v3-turbo", language: str = "en",
                 timeout_s: float = 10.0, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(timeout=timeout_s, transport=transport, 
                                         headers={"Authorization": f"Bearer {api_key}"})
        self._model = model
        self._language = language

    async def transcribe(self, samples: np.ndarray) -> str:
        return " ".join(w.text for w in await self.transcribe_words(samples))

    async def transcribe_words(self, samples: np.ndarray, prompt: str | None = None) -> list[Word]:
        data = {"model": self._model, "language": self._language, 
                "response_format": "verbose_json", "timestamp_granularities[]": ["word"]}
        if prompt:
            data["prompt"] = prompt

        files = {"file": ("window.wav", to_wav(samples), "audio/wav")}

        for _ in range(3):
            try:
                res = await self._client.post(GROQ_URL, data=data, files=files)
            except httpx.HTTPError as e:
                raise TranscriptionError(f"Groq unreachable: {e!r}") from e
            if res.status_code != 429:
                break
            wait = float(res.headers.get("retry-after", 1))
            if wait > MAX_RETRY_WAIT_S:
                break
            await asyncio.sleep(wait)

        if res.status_code != 200:
            raise TranscriptionError(f"Groq {res.status_code}: {res.text[:200]}")
        
        # return [Word(w["start"], w["end"], w["word"].strip()) for w in res.json().get("words", []) if w["word"].strip()]
        words = []
        for w in res.json().get("words", []):
            if w["word"].strip():
                words.append(Word(w["start"], w["end"], w["word"].strip()))

        return words