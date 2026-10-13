## DB
- Postgres + pgvector (pgvector/pgvector:pg16 locally; AWS hosting TBD)

## Backend
- Audio capture: Electron with native macOS ScreenCaptureKit loopback
- Transcription: OpenAI Whisper (API)
- LLM: Sonnet 5
- API: FastAPI, SQLAlchemy, Alembic
- Agentic framework: Proprietary

## Frontend
- Electron.js (Node.js)
- Desktop controls: nut.js

## Deployment
- AWS (single provider; specific services TBD)

## Docker Containers
- FastAPI backend
- Postgres + pgvector (dev)
