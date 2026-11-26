"""GroqWhisperTranscriber against a fake Groq (httpx.MockTransport), so nothing goes online."""
import io
import json
import time
import wave

import httpx
import numpy as np
import pytest

from app.config import Settings
from app.stt.factory import make_transcriber
from app.stt.groq import GroqWhisperTranscriber, to_wav
from app.stt.transcriber import SAMPLE_RATE, TranscriptionError, Word

pytestmark = pytest.mark.anyio

WORDS = {"words": [
    {"word": " Hello", "start": 0.1, "end": 0.4},
    {"word": " ", "start": 0.4, "end": 0.5},   # Whisper sometimes returns blank words
    {"word": "world.", "start": 0.5, "end": 0.9},
]}


class FakeGroq:
    """Answers each request with the next reply in `replies`, and keeps every request."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def groq(fake: FakeGroq) -> GroqWhisperTranscriber:
    return GroqWhisperTranscriber("gsk_test", transport=httpx.MockTransport(fake))


def ok(body=WORDS) -> httpx.Response:
    return httpx.Response(200, json=body)


def rate_limited(retry_after: str) -> httpx.Response:
    return httpx.Response(429, headers={"retry-after": retry_after}, json={"error": "rate limited"})


def speech(seconds: float = 1.0) -> np.ndarray:
    return np.full(round(seconds * SAMPLE_RATE), 0.1, dtype=np.float32)


# --- the WAV Groq receives ---

def test_wav_is_16_bit_mono_at_16_khz():
    samples = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
    with wave.open(io.BytesIO(to_wav(samples))) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, SAMPLE_RATE)
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    assert pcm.tolist() == [0, 16383, -16383, 32767, -32767]


def test_wav_clips_out_of_range_samples():
    with wave.open(io.BytesIO(to_wav(np.array([2.0, -3.0], dtype=np.float32)))) as w:
        pcm = np.frombuffer(w.readframes(2), dtype="<i2")
    assert pcm.tolist() == [32767, -32767]


# --- a normal reply ---

async def test_reply_becomes_words_without_blanks():
    words = await groq(FakeGroq(ok())).transcribe_words(speech())
    assert words == [Word(0.1, 0.4, "Hello"), Word(0.5, 0.9, "world.")]


async def test_request_asks_for_word_timestamps_and_sends_the_prompt():
    fake = FakeGroq(ok())
    await groq(fake).transcribe_words(speech(), prompt="Lecture 4: Glycolysis.")
    request = fake.requests[0]
    body = request.content
    assert request.headers["authorization"] == "Bearer gsk_test"
    for field, value in [("model", b"whisper-large-v3-turbo"), ("language", b"en"),
                         ("response_format", b"verbose_json"), ("timestamp_granularities[]", b"word"),
                         ("prompt", b"Lecture 4: Glycolysis.")]:
        assert f'name="{field}"\r\n\r\n'.encode() + value in body, field
    assert b'filename="window.wav"' in body


async def test_no_prompt_field_without_a_prompt():
    fake = FakeGroq(ok())
    await groq(fake).transcribe_words(speech())
    assert b'name="prompt"' not in fake.requests[0].content


async def test_transcribe_joins_the_words():
    assert await groq(FakeGroq(ok())).transcribe(speech()) == "Hello world."


# --- failures ---

async def test_short_rate_limit_is_waited_out():
    fake = FakeGroq(rate_limited("0"), ok())
    assert len(await groq(fake).transcribe_words(speech())) == 2
    assert len(fake.requests) == 2


async def test_long_rate_limit_gives_up_without_waiting():
    fake = FakeGroq(rate_limited("3600"))   # e.g. the daily quota ran out
    start = time.perf_counter()
    with pytest.raises(TranscriptionError, match="429"):
        await groq(fake).transcribe_words(speech())
    assert time.perf_counter() - start < 1
    assert len(fake.requests) == 1


async def test_gives_up_after_three_rate_limits():
    fake = FakeGroq(rate_limited("0"), rate_limited("0"), rate_limited("0"))
    with pytest.raises(TranscriptionError, match="429"):
        await groq(fake).transcribe_words(speech())
    assert len(fake.requests) == 3


async def test_server_error_raises_with_status_and_body():
    fake = FakeGroq(httpx.Response(500, text="upstream exploded"))
    with pytest.raises(TranscriptionError, match="500: upstream exploded"):
        await groq(fake).transcribe_words(speech())


async def test_network_error_raises_with_its_type():
    fake = FakeGroq(httpx.ConnectError("[Errno 61] Connection refused"))
    with pytest.raises(TranscriptionError, match="unreachable: ConnectError"):
        await groq(fake).transcribe_words(speech())


# --- make_transcriber ---

def settings(**overrides) -> Settings:
    # _env_file=None so the repo .env (which has a real key) can't change what we're asserting
    return Settings(_env_file=None, database_url="postgresql://x", **overrides)


def test_factory_builds_groq_from_settings():
    t = make_transcriber(settings(stt_provider="groq", groq_api_key="gsk_x"))
    assert isinstance(t, GroqWhisperTranscriber)


def test_factory_groq_needs_a_key():
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        make_transcriber(settings(stt_provider="groq"))


def test_factory_rejects_unknown_provider():
    with pytest.raises(ValueError, match="expected 'mlx' or 'groq'"):
        make_transcriber(settings(stt_provider="whisperx"))
