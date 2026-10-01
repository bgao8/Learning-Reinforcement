### Timeline

## Week 1: Foundations

Days 1–2: Audio capture spike (go/no-go, with BlackHole as fallback)
Overlay window with click-through toggling
docker-compose setup with Postgres and pgvector, plus the initial schema
Agent framework: model client and tool registry

## Week 2: Pipeline

Agent framework: agent loop, structured output, tracing to Postgres
Chunked audio upload from Electron to the backend
Transcription with silence filtering
A rolling transcript buffer per session

## Week 3: Quiz loop

Checkpoint detection based on transcript length and topic shifts
A tutor agent that generates questions grounded in the transcript
Pausing via media keys, the question card UI, and LLM grading
Attempts saved to the database

## Week 4: Adaptation

Concept extraction and deduplication with pgvector
Elo mastery scores per concept
Adaptive prompts that target weak concepts and preferred question styles

## Week 5: Quality and polish

Eval harness: a labeled set, grader agreement, and groundedness checks
SM-2 review mode, if time allows
README with an architecture diagram, plus a demo video

# Done when: a 20-minute lecture produces grounded questions at sensible points, results persist, and the next session adapts.