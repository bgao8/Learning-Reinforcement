"""make_transcriber(): build the speech-to-text backend chosen in config."""
from app.config import Settings, settings as default_settings
from app.stt.transcriber import Transcriber


def make_transcriber(s: Settings = default_settings) -> Transcriber:
    if s.stt_provider == "mlx":
        from app.stt.mlx import MlxWhisperTranscriber
        return MlxWhisperTranscriber(model=s.stt_model, language=s.stt_language)

    if s.stt_provider == "groq":
        if not s.groq_api_key:
            raise ValueError("stt_provider 'groq' needs GROQ_API_KEY in the repo-root .env")
        from app.stt.groq import GroqWhisperTranscriber
        return GroqWhisperTranscriber(
            s.groq_api_key, model=s.groq_stt_model, language=s.stt_language, timeout_s=s.groq_timeout_s,
        )

    raise ValueError(f"unknown stt_provider {s.stt_provider!r} (expected 'mlx' or 'groq')")
