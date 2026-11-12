## DB
- Postgres + pgvector (pgvector/pgvector:pg16 locally; AWS hosting TBD)

## Backend
- Audio capture: Electron with native macOS ScreenCaptureKit loopback
- API: FastAPI, SQLAlchemy, Alembic
- Agentic framework: Proprietary, with a provider-agnostic model client (#9)

## Models (hybrid local + API)
Each task goes to the cheapest model that is good enough for it, decided by measurement (#27), not guesswork.

| Task | Model | Why |
|---|---|---|
| Transcription (#15) | Local Whisper on Apple Silicon (whisper.cpp / faster-whisper / mlx-whisper); OpenAI Whisper API as fallback | Runs constantly on lecture audio: free, private, no upload latency |
| Topic-shift detection (#18) | Small local model (Ollama or MLX) | Frequent, cheap classification; an API call every few seconds is wasteful |
| Concept embeddings (#24) | Local embedding model (sentence-transformers or Ollama) | Small and fast; pgvector doesn't care where vectors come from |
| Question generation (#19), grading (#22) | Claude Sonnet 5 | Quality matters most here; small local models are noticeably worse at grounded questions and fair grading |

## Frontend
- Electron.js (Node.js)
- Desktop controls: a small Swift helper (`client/native/mediakey.swift`) posts the play/pause media key (#20). nut.js was the original plan, but its official prebuilt packages are no longer free, and one key press doesn't justify a native npm dependency. An osascript/JXA version was tried first and failed silently: JXA can't bridge `NSEvent.cgEvent`, so it posted an empty event. Revisit nut.js if broader desktop control is needed.

## Deployment
- AWS (single provider; specific services TBD)

## Docker Containers
- FastAPI backend
- Postgres + pgvector (dev)
