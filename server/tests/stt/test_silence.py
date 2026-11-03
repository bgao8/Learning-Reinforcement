import numpy as np

from app.stt.silence import RMS_FLOOR, is_silent, rms
from app.stt.transcriber import SAMPLE_RATE


def tone(amplitude: float, seconds: float = 1.0, hz: float = 440.0) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def test_digital_silence_is_silent():
    assert is_silent(np.zeros(SAMPLE_RATE, dtype=np.float32))


def test_empty_chunk_is_silent():
    assert rms(np.array([], dtype=np.float32)) == 0.0
    assert is_silent(np.array([], dtype=np.float32))


def test_speech_level_audio_is_not_silent():
    # -20 dBFS, roughly normal playback
    assert not is_silent(tone(0.1))


def test_rms_of_sine_is_amplitude_over_root_two():
    assert np.isclose(rms(tone(0.5)), 0.5 / np.sqrt(2), rtol=1e-3)


def test_floor_boundary():
    just_below = tone(RMS_FLOOR * np.sqrt(2) * 0.9)
    just_above = tone(RMS_FLOOR * np.sqrt(2) * 1.1)
    assert is_silent(just_below)
    assert not is_silent(just_above)
