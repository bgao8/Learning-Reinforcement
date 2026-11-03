"""make_transcriber(): build the speech-to-text backend chosen in config."""
from app.config import Settings, settings as default_settings
from app.stt.transcriber import Transcriber


def make_transcriber(s: Settings = default_settings) -> Transcriber:
    if s.stt_provider == "mlx":
        from app.stt.mlx import MlxWhisperTranscriber
        return MlxWhisperTranscriber(model=s.stt_model, language=s.stt_language)

    raise ValueError(f"unknown stt_provider {s.stt_provider!r} (expected 'mlx')")