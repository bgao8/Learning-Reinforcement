"""Silence gate: skip chunks with no audio before spending a transcription on them."""
import numpy as np


RMS_FLOOR = 0.0003

def rms(samples: np.ndarray) -> float:
    """Average loudness: square each sample, take the mean, then square root."""
    if samples.size == 0:
        return 0.0

    return float(np.sqrt(np.mean(np.square(samples))))

def is_silent(samples: np.ndarray, floor: float = RMS_FLOOR) -> bool:
    return rms(samples) < floor