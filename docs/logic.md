## Transcription
- Look at ScreenCaptureKit output, run through Whisper
- Run Whisper locally on Apple Silicon first (whisper.cpp / faster-whisper / mlx-whisper); Whisper API as fallback
- Whisper wants 16 kHz mono: resample from the AudioContext rate (usually 48 kHz)


## Topic Shift
- *Option 1*: Purely LLM logic
- Runs every few seconds, so use a small local model (Ollama / MLX), not an API call
- Consider sensitivity to topic switch
- Pause video/recording, trigger quiz


## Quiz
- How to extract from logic base
- Prompt
