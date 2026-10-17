# Learning Reinforcement (WIP)
A learning reinforcement tool that quizzes you on the lecture you're watching, as you watch it, and adapts questions based on what you already know.

**MVP in progress.**

## User Story
As a student watching a recorded lecture, I want to be quizzed on what I just heard, at sensible moments, so that I actively recall the material and spend my review time on the concepts I'm still weak on.

## The Problem
In a classroom, a teacher stops to check understanding: they ask questions, notice confusion, and revisit weak spots. 

This classic teaching method is lost in recorded online lectures, which tend to be unengaging and forgettable. There is nothing that makes you actively recall what you just heard.

## How It Works
A small overlay runs on top of whatever you're watching. It:
1. Listens to your Mac's system audio and transcribes it.
2. Detects topic changes.
3. At a natural checkpoint (a topic shift, or enough new material), pauses the video and asks a question grounded in what was just said.
4. Grades your answer and updates a mastery score for each concept.
5. Adapts future questions to reinforce topics you're still weak on.

**Why system audio?**
- Platform APIs (like YouTube's) lock functionality to one site. Capturing system audio makes it universal to all websites, downloaded videos, and even video calls (Zoom, Meet).

The tradeoff is that ScreenCaptureKit is limited to macOS.

## Stack
- **Audio ingestion:** Apple ScreenCaptureKit
- **Transcription:** Whisper, run locally on Apple Silicon (OpenAI Whisper API as fallback)
- **LLMs:** Claude Sonnet 5 for question generation and grading; small local models (Ollama / MLX) for topic-shift detection and embeddings
- **Backend:** FastAPI, SQLAlchemy, Alembic
- **Data:** Postgres + pgvector
- **Frontend:** Electron.js (Node.js)
- **Desktop controls:** nut.js
- **Cloud:** AWS

## Design Decisions
- **Grounded questions.** Questions are generated only from the transcript of what was actually said, so the LLM quizzes you on the lecture, not on whatever it thinks the topic should contain.
- **Checkpoints, not timers.** Quizzes trigger on transcript length plus topic shifts, so questions land at natural breaks instead of mid-sentence.
- **Elo-style mastery per concept.** Each answer updates a score for (you, concept), weighted by question difficulty. Future questions target low-mastery concepts.
- **Hybrid local + API models.** A provider-agnostic model layer routes each task to the cheapest model that is good enough: high-frequency work (transcription, topic shifts, embeddings) runs locally; quality-critical work (questions, grading) goes to Claude. The split is decided by evals, not guesswork.
- **Concept dedup with pgvector.** Concepts extracted from different lectures are matched by embedding similarity, so "gradient descent" in one video and "GD" in another share one mastery score.

## MVP Roadmap
- [x] **M0 Housekeeping:** repo hygiene, audio-capture spike (GO: native ScreenCaptureKit loopback, no BlackHole)
- [ ] **W1 Foundations:** Electron app, overlay window, Postgres + pgvector, agent framework basics (provider-agnostic model client: Anthropic + local)
- [ ] **W2 Pipeline:** agent loop + tracing, chunked audio upload, local Whisper transcription with silence filtering, rolling transcript buffer
- [ ] **W3 Quiz loop:** checkpoint detection, grounded question generation, media-key pause, question card UI, LLM grading
- [ ] **W4 Adaptation:** concept extraction + dedup, Elo mastery, adaptive prompting
- [ ] **W5 Quality & polish:** eval harness (grader agreement, groundedness, local vs. API model comparison), SM-2 review mode (stretch), architecture diagram + demo

**Done when:** a 20-minute lecture produces grounded questions at sensible points, results persist, and the next session adapts.

## Status
macOS only. Early development: the Electron client lives in `client/`, the FastAPI backend in `server/`. Setup instructions will land with the architecture diagram and demo.
